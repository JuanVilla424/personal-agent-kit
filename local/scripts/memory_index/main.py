#!/usr/bin/env python3
"""Semantic memory index CLI — index and query runbook docs via Qdrant."""

import argparse
import hashlib
import json
import re
import sys
import time
import uuid
import warnings
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent / "notify"))
from ops import metrics_push

from fastembed import TextEmbedding
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

import config
from logger import logger

VECTOR_DIM = 384


def _cache_dir() -> str:
    return str(Path(__file__).parent / ".cache" / "fastembed")


def _load_model() -> TextEmbedding:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return TextEmbedding(model_name=config.EMBEDDING_MODEL, cache_dir=_cache_dir())


def stable_id(source: str, section: str) -> str:
    """Return a deterministic UUID derived from source path and section name."""
    digest = hashlib.sha256(f"{source}::{section}".encode()).digest()
    return str(uuid.UUID(bytes=digest[:16]))


def get_client() -> Optional[QdrantClient]:
    """Return a connected Qdrant client, or None if the server is unreachable.

    Local default (no api key / http) behaves exactly as before. When pointed at
    the central server, api_key + https engage automatically from config.
    """
    try:
        # https explicit (False by default): qdrant-client auto-enables TLS when an
        # api_key is set, which breaks against a plain-HTTP qdrant.
        kwargs = {
            "host": config.QDRANT_HOST,
            "port": config.QDRANT_PORT,
            "timeout": 3,
            "https": config.QDRANT_HTTPS,
        }
        if config.QDRANT_API_KEY:
            kwargs["api_key"] = config.QDRANT_API_KEY
        client = QdrantClient(**kwargs)
        client.get_collections()
        return client
    except Exception:  # pylint: disable=broad-except
        return None


def chunk_markdown(path: Path, docs_parent: Path) -> List[dict]:
    """Split a markdown file into section-level chunks."""
    text = path.read_text(encoding="utf-8")
    stem = path.stem
    case_id = stem
    source = str(path.relative_to(docs_parent))

    chunks: List[dict] = []
    section = "(intro)"
    lines: List[str] = []

    def flush() -> None:
        body = "\n".join(lines).strip()
        if len(body) > 30:
            chunks.append(
                {
                    "source": source,
                    "case_id": case_id,
                    "title": stem,
                    "section": section,
                    "text": body[:2000],
                }
            )

    for line in text.splitlines():
        if re.match(r"^#{2,3} ", line):
            flush()
            section = line.lstrip("#").strip()
            lines = []
        else:
            lines.append(line)
    flush()
    return chunks


def get_target_docs(docs_root: Path) -> List[Path]:
    """Return all documents to index: the runbooks."""
    runbooks = [docs_root / "TROUBLESHOOTING.md", docs_root / "SETUP-TROUBLESHOOTING.md"]
    return [p for p in runbooks if p.exists()]


def ensure_collection(client: QdrantClient) -> None:
    """Recreate the vector collection from scratch.

    A plain upsert never removes vectors of deleted lessons (phantom vectors:
    a closed/removed CA-* stays searchable forever). Recreating the collection
    on every full index keeps Qdrant in exact sync with what is on disk — the
    correlation engine must never match a lesson that no longer exists.
    """
    client.recreate_collection(
        collection_name=config.QDRANT_COLLECTION,
        vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
    )
    logger.info("Collection '%s' recreated (clean rebuild).", config.QDRANT_COLLECTION)


_METRICS_STATE = Path(__file__).parent / ".metrics-state"


def _read_count(name: str) -> int:
    try:
        f = _METRICS_STATE / name
        raw = f.read_text().strip() if f.exists() else ""
        return int(raw) if raw.isdigit() else 0
    except Exception:
        return 0


def _bump(name: str) -> int:
    try:
        _METRICS_STATE.mkdir(exist_ok=True)
        value = _read_count(name) + 1
        (_METRICS_STATE / name).write_text(str(value))
        return value
    except Exception:
        return 0


def _record_query(hit: bool, top_score: float) -> None:
    """Persist + push query telemetry. Never raises — search must not break.

    Uses push_run() (stdlib fallback) because this venv lacks prometheus_client.
    """
    try:
        queries = _bump("queries.count")
        if hit:
            _bump("hits.count")
        metrics_push.push_run(
            "memory_index_query",
            memory_index_queries_total=float(queries),
            memory_index_hits_total=float(_read_count("hits.count")),
            memory_index_last_query_top_score=float(top_score),
        )
    except Exception:
        pass


def cmd_index(_args: argparse.Namespace):
    """Index all target documents into the Qdrant collection. Returns stats dict."""
    client = get_client()
    if client is None:
        logger.error(
            "Cannot reach Qdrant at %s:%s — run: docker compose up -d",
            config.QDRANT_HOST,
            config.QDRANT_PORT,
        )
        sys.exit(1)

    ensure_collection(client)
    docs_root = Path(config.DOCS_ROOT)
    docs_parent = docs_root.parent
    all_chunks: List[dict] = []

    for doc in get_target_docs(docs_root):
        chunks = chunk_markdown(doc, docs_parent)
        logger.info("  %s -> %d chunks", doc.name, len(chunks))
        all_chunks.extend(chunks)

    if not all_chunks:
        logger.warning("No chunks found — check DOCS_ROOT: %s", config.DOCS_ROOT)
        sys.exit(0)

    model = _load_model()
    texts = [c["text"] for c in all_chunks]
    logger.info("Generating embeddings for %d chunks...", len(texts))
    vectors = [v.tolist() for v in model.embed(texts)]

    points = [
        PointStruct(
            id=stable_id(c["source"], c["section"]),
            vector=vec,
            payload={k: c[k] for k in ("source", "case_id", "title", "section", "text")},
        )
        for c, vec in zip(all_chunks, vectors)
    ]
    client.upsert(collection_name=config.QDRANT_COLLECTION, points=points)
    logger.info("Upserted %d chunks into '%s'.", len(points), config.QDRANT_COLLECTION)

    # Aggregate counts for telemetry.
    target_docs = get_target_docs(docs_root)
    newest_ts = 0.0
    for doc in target_docs:
        try:
            newest_ts = max(newest_ts, doc.stat().st_mtime)
        except OSError:
            pass
    return {
        "docs": len(target_docs),
        "chunks": len(points),
        "newest_ts": newest_ts,
        "avg_chunks": len(points) / max(len(target_docs), 1),
    }


def _trust_label(source: str) -> str:
    """Return a trust level tag for a result source.

    All currently indexed sources are internal docs. The label is explicit so
    that if external sources are ever added, this stays able to distinguish them
    from potentially untrusted/injection-risk content.
    """
    internal = ("TROUBLESHOOTING", "SETUP-TROUBLESHOOTING")
    if any(marker in source for marker in internal):
        return "[INTERNAL SOURCE ✅]"
    return "[EXTERNAL SOURCE ⚠️]"


def cmd_query(args: argparse.Namespace) -> None:
    """Search the semantic index and print the closest matching cases."""
    client = get_client()
    if client is None:
        logger.warning("Qdrant not reachable — falling back to keyword search in INDEX.md")
        sys.exit(0)

    if not client.collection_exists(config.QDRANT_COLLECTION):
        logger.warning("Collection '%s' not found — run: main.py index", config.QDRANT_COLLECTION)
        sys.exit(0)

    model = _load_model()
    query_vector = list(model.embed([args.text]))[0].tolist()

    response = client.query_points(
        collection_name=config.QDRANT_COLLECTION,
        query=query_vector,
        limit=args.top_k,
        score_threshold=args.threshold,
        with_payload=True,
    )
    results = response.points
    _record_query(bool(results), results[0].score if results else 0.0)

    if not results:
        logger.info(
            "No semantic matches above %.2f — keyword search in INDEX.md applies.",
            args.threshold,
        )
        sys.exit(0)

    if args.as_json:
        hits = [
            {
                "case_id": r.payload.get("case_id", ""),
                "source": r.payload.get("source", ""),
                "section": r.payload.get("section", ""),
                "score": round(r.score, 4),
                "trust": _trust_label(r.payload.get("source", "")),
                "snippet": r.payload.get("text", "")[:200],
            }
            for r in results
        ]
        print(json.dumps(hits, ensure_ascii=False, indent=2))
        return

    for r in results:
        payload = r.payload or {}
        trust = _trust_label(payload.get("source", ""))
        print(
            f"  {trust} [{r.score:.3f}] {payload.get('case_id', '-')} · "
            f"{payload.get('source', '')} · {payload.get('section', '')}"
        )
        snippet = payload.get("text", "")[:150].replace("\n", " ")
        print(f"         {snippet}...")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Semantic memory index for cloud diagnostics")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("index", help="Index docs into Qdrant")

    q_parser = sub.add_parser("query", help="Search the semantic index by symptom description")
    q_parser.add_argument("text", help="Symptom description to search for")
    q_parser.add_argument("--json", dest="as_json", action="store_true", help="Output as JSON")
    q_parser.add_argument("--top-k", type=int, default=config.TOP_K, dest="top_k")
    q_parser.add_argument("--threshold", type=float, default=config.SCORE_THRESHOLD)

    parsed = parser.parse_args()
    if parsed.cmd == "index":
        run_start = time.monotonic()
        stats = cmd_index(parsed)
        # Centralize run results in Prometheus (pushgateway → central scrape)
        gauges = {}
        if stats:
            gauges = {
                "memory_index_docs_total": float(stats["docs"]),
                "memory_index_chunks_total": float(stats["chunks"]),
                "memory_index_avg_chunks_per_doc": float(stats["avg_chunks"]),
                "memory_index_newest_doc_timestamp_seconds": float(stats["newest_ts"]),
            }
        metrics_push.push_run(
            "memory_index", duration_seconds=time.monotonic() - run_start, **gauges
        )
    elif parsed.cmd == "query":
        cmd_query(parsed)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
