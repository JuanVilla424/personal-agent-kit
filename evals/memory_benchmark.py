#!/usr/bin/env python3
"""memory_benchmark.py — PAK's memory against a Hermes-like memory, on a public synthetic dataset.

The dataset (evals/datasets/memory-recall.jsonl) is a fictional owner: 60 memories, 10 of them
facts that change over time, and 54 questions of four kinds: an exact identifier, a paraphrase, the
current value of a changed fact, and a question in the other language. Before each memory the
runner writes 6 ordinary notes (seeded, so every run is the same), 360 in all: a store that has
been used for a while.

Systems:
  pak             memory_service itself (hybrid search, replacement by state_key), through its
                  HTTP API on an in-memory Qdrant, with each fusion setting
  pak-dense       the first version: dense search only, no replacement
  bm25            lexical search only
  hermes-like     Hermes' documented memory: MEMORY.md (2,200 chars) and USER.md (1,375 chars)
                  injected whole, newest first, plus FTS5 search over everything ever written

A question counts as found at rank r when its memory is r-th and no outdated version of the same
fact ranks above it: an agent that sees the old value first answers with it. For hermes-like a
memory inside the injected files counts as rank 1, and the files hold only the newest version of
each fact: both assumptions favor it.

The fusion setting is chosen on the dev questions and every system is reported on the test ones.
No model is called; the embeddings run locally.

Usage: python3 evals/memory_benchmark.py [--cache-dir DIR] [--out FILE]
"""

import argparse
import json
import os
import random
import secrets
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MEM_DIR = REPO / "local" / "scripts" / "memory_index"
DATASET = REPO / "evals" / "datasets" / "memory-recall.jsonl"
NOISE_PER_MEMORY = 6
NOISE_SEED = 7
K = 5
HERMES_MEMORY_CHARS = 2200
HERMES_USER_CHARS = 1375
# the in-memory service of this run only needs some token: a fresh one each run
TOKEN = secrets.token_hex(16)
FUSIONS = [("convex", 0.3), ("convex", 0.5), ("convex", 0.7), ("adaptive", 0.7), ("rrf", 0.0)]

NOISE_VERBS = [
    "Remember",
    "Note",
    "Follow up on",
    "Ask about",
    "Check",
    "Plan",
    "Reschedule",
    "Pay",
]
NOISE_TOPICS = [
    "the garden hose",
    "groceries for the week",
    "the book club pick",
    "a dentist appointment",
    "the car wash coupon",
    "the neighborhood meeting",
    "a podcast episode",
    "the plumber visit",
    "a card for a coworker",
    "the recycling schedule",
    "a flight to Lisbon",
    "the library late fee",
    "a pizza recipe",
    "the bike tune-up",
    "the electricity bill",
    "an online course",
    "the window cleaner",
    "a concert ticket",
    "the soccer practice",
    "a jigsaw puzzle",
]
NOISE_WHEN = ["on Tuesday", "next week", "before the weekend", "this afternoon", "in March"]
NOISE_WITH = ["with Sam", "with the landlord", "for the kids", "with Priya", "by phone", "online"]


def load_dataset() -> tuple[list[dict], list[dict]]:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if r["type"] == "memory"], [r for r in rows if r["type"] == "question"]


def build_stream(memories: list[dict]) -> list[dict]:
    """The order everything was written in: ordinary notes before each memory."""
    rng = random.Random(NOISE_SEED)
    stream, n = [], 0
    for memory in memories:
        for _ in range(NOISE_PER_MEMORY):
            text = (
                f"{rng.choice(NOISE_VERBS)} {rng.choice(NOISE_TOPICS)} {rng.choice(NOISE_WHEN)} "
                f"{rng.choice(NOISE_WITH)} (note {n})"
            )
            stream.append({"id": f"n{n:03d}", "text": text, "category": "other"})
            n += 1
        stream.append(memory)
    return stream


def stale_versions(stream: list[dict]) -> dict[str, set[str]]:
    """For each memory, the outdated versions of the same fact (empty for most)."""
    by_key: dict[str, list[str]] = {}
    for entry in stream:
        if entry.get("state_key"):
            by_key.setdefault(entry["state_key"], []).append(entry["id"])
    stale: dict[str, set[str]] = {}
    for versions in by_key.values():
        for i, entry_id in enumerate(versions):
            stale[entry_id] = set(versions[:i])
    return stale


def rank_of(ranking: list[str], answer: str, stale: set[str]) -> int | None:
    """The answer's rank within K, or None: a miss, or an outdated version seen before it."""
    for position, entry_id in enumerate(ranking[:K], start=1):
        if entry_id in stale:
            return None
        if entry_id == answer:
            return position
    return None


def metrics(ranks: list[int | None]) -> dict[str, float]:
    n = len(ranks) or 1
    return {
        "hit@1": round(sum(1 for r in ranks if r == 1) / n, 3),
        "hit@5": round(sum(1 for r in ranks if r is not None) / n, 3),
        "mrr@5": round(sum(1 / r for r in ranks if r is not None) / n, 3),
    }


# ── The systems ──────────────────────────────────────────────────────────────────────────────────


class Pak:
    """memory_service through its HTTP API, on an in-memory Qdrant and the real embedding model."""

    def __init__(self, stream: list[dict], cache_dir: str):
        os.environ.setdefault("MEMORY_ALLOW_NO_AUTH", "true")  # the import-time auth check
        sys.path.insert(0, str(MEM_DIR))
        import memory_service as ms
        from fastapi.testclient import TestClient
        from fastembed import TextEmbedding
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, VectorParams

        self.ms = ms
        self.qdrant = QdrantClient(location=":memory:")
        for collection in (ms.MEMORY_COLLECTION, ms.USER_COLLECTION):
            self.qdrant.create_collection(
                collection,
                vectors_config=VectorParams(size=ms.VECTOR_DIM, distance=Distance.COSINE),
            )
        model = TextEmbedding(model_name=ms.config.EMBEDDING_MODEL, cache_dir=cache_dir)
        texts = [entry["text"] for entry in stream]
        self.vectors = dict(zip(texts, (v.tolist() for v in model.embed(texts))))
        self.model = model
        ms._client_get = lambda: self.qdrant
        ms._embed = self.embed
        ms._push_metrics = lambda: None
        ms.USER_TOKENS = {TOKEN: "owner"}
        ms.MEMORY_ADMIN_TOKEN = ""
        ms.ALLOW_NO_AUTH = False
        self.api = TestClient(ms.app)
        self.by_text: dict[str, str] = {}
        for entry in stream:
            body = {"text": entry["text"], "category": entry.get("category", "other")}
            if entry.get("state_key"):
                body["state_key"] = entry["state_key"]
            response = self.api.post("/memory/add", json=body, headers={"x-memory-token": TOKEN})
            response.raise_for_status()
            self.by_text[entry["text"]] = entry["id"]

    def embed(self, text: str) -> list[float]:
        if text not in self.vectors:
            self.vectors[text] = next(iter(self.model.embed([text]))).tolist()
        return self.vectors[text]

    def search(self, question: str, fusion: str, alpha: float) -> list[str]:
        self.ms.FUSION, self.ms.FUSION_ALPHA = fusion, alpha
        response = self.api.get(
            "/memory/search", params={"q": question, "k": K}, headers={"x-memory-token": TOKEN}
        )
        response.raise_for_status()
        return [self.by_text[r["text"]] for r in response.json()["results"]]

    def dense_only(self, question: str) -> list[str]:
        points = self.qdrant.query_points(
            collection_name=self.ms.USER_COLLECTION, query=self.embed(question), limit=K
        ).points
        return [self.by_text[p.payload["text"]] for p in points]


class Bm25Only:
    def __init__(self, stream: list[dict]):
        sys.path.insert(0, str(MEM_DIR))
        import memory_core as core

        self.index = core.BM25Index((entry["id"], entry["text"]) for entry in stream)

    def search(self, question: str) -> list[str]:
        return self.index.ranked(question, K)


class HermesLike:
    """Two bounded files injected whole, newest first, and FTS5 over everything ever written."""

    def __init__(self, stream: list[dict]):
        sys.path.insert(0, str(MEM_DIR))
        import memory_core as core

        self.words = core.words
        replaced = {e for stale in stale_versions(stream).values() for e in stale}
        budgets = {"user": HERMES_USER_CHARS, "memory": HERMES_MEMORY_CHARS}
        self.injected: set[str] = set()
        for entry in reversed(stream):
            if entry["id"] in replaced:
                continue  # generous: the agent always replaced the outdated line
            target = "user" if entry.get("category") == "style" else "memory"
            size = len(entry["text"]) + 3
            if size <= budgets[target]:
                budgets[target] -= size
                self.injected.add(entry["id"])
        self.db = sqlite3.connect(":memory:")
        # generous: Porter stemming and accent folding, which FTS5 does not do by default
        self.db.execute(
            "CREATE VIRTUAL TABLE notes USING fts5(entry_id UNINDEXED, text, "
            "tokenize = 'porter unicode61 remove_diacritics 2')"
        )
        self.db.executemany(
            "INSERT INTO notes VALUES (?, ?)", [(e["id"], e["text"]) for e in stream]
        )

    def search(self, question: str, answer: str) -> list[str]:
        if answer in self.injected:
            return [answer]
        terms = self.words(question)  # FTS5 stems the query itself
        if not terms:
            return []
        query = " OR ".join('"' + term.replace('"', "") + '"' for term in terms)
        rows = self.db.execute(
            "SELECT entry_id FROM notes WHERE notes MATCH ? ORDER BY bm25(notes) LIMIT ?",
            (query, K),
        ).fetchall()
        return [row[0] for row in rows]


# ── The run ──────────────────────────────────────────────────────────────────────────────────────


def score(rankings: dict[str, list[str]], questions: list[dict], stale: dict) -> dict:
    """Metrics per split and kind for one system."""
    out: dict = {}
    for split in ("dev", "test", "all"):
        chosen = [q for q in questions if split == "all" or q["split"] == split]
        ranks = {
            q["id"]: rank_of(rankings[q["id"]], q["answer"], stale.get(q["answer"], set()))
            for q in chosen
        }
        out[split] = metrics(list(ranks.values()))
        for kind in sorted({q["kind"] for q in chosen}):
            out[split][kind] = metrics([ranks[q["id"]] for q in chosen if q["kind"] == kind])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--cache-dir", default=str(MEM_DIR / ".cache" / "fastembed"))
    ap.add_argument("--out", default=str(REPO / "temp" / "memory-benchmark" / "result.json"))
    args = ap.parse_args()

    started = time.time()
    memories, questions = load_dataset()
    stream = build_stream(memories)
    stale = stale_versions(stream)
    pak = Pak(stream, args.cache_dir)
    bm25 = Bm25Only(stream)
    hermes = HermesLike(stream)

    systems: dict[str, dict[str, list[str]]] = {}
    for fusion, alpha in FUSIONS:
        name = f"pak ({fusion}{'' if fusion == 'rrf' else f' {alpha}'})"
        systems[name] = {q["id"]: pak.search(q["text"], fusion, alpha) for q in questions}
    systems["pak-dense"] = {q["id"]: pak.dense_only(q["text"]) for q in questions}
    systems["bm25"] = {q["id"]: bm25.search(q["text"]) for q in questions}
    systems["hermes-like"] = {q["id"]: hermes.search(q["text"], q["answer"]) for q in questions}

    results = {name: score(rankings, questions, stale) for name, rankings in systems.items()}
    pak_names = [name for name in results if name.startswith("pak (")]
    chosen = max(
        pak_names,
        key=lambda n: (
            results[n]["dev"]["hit@1"],
            results[n]["dev"]["hit@5"],
            results[n]["dev"]["mrr@5"],
        ),
    )
    report = {
        "dataset": {"memories": len(memories), "notes": len(stream) - len(memories)},
        "questions": {s: sum(q["split"] == s for q in questions) for s in ("dev", "test")},
        "chosen_on_dev": chosen,
        "hermes_injected": len(hermes.injected),
        "seconds": round(time.time() - started, 1),
        "results": results,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(f"chosen on dev: {chosen}   (written to {out})")
    print(f"{'system':22} {'split':5} {'hit@1':>6} {'hit@5':>6} {'mrr@5':>6}")
    for name, by_split in results.items():
        for split in ("dev", "test"):
            m = by_split[split]
            print(f"{name:22} {split:5} {m['hit@1']:6.3f} {m['hit@5']:6.3f} {m['mrr@5']:6.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
