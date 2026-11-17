#!/usr/bin/env python3
"""memory_service.py — local agent-memory API (the SINGLE writer).

The agent's personalization layer lives in the `agent_memory` Qdrant collection
(primary store — NOT a cache of lessons). This service is the only process that
writes to it: local callers reach it over HTTP (no write-key, no fastembed on
their end). Embedding is done server-side for model consistency.

Run (server): .venv/bin/python local/scripts/memory_index/memory_service.py
"""

import asyncio
import hashlib
import os
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

THIS = Path(__file__).resolve()
sys.path.insert(0, str(THIS.parent))
sys.path.insert(0, str(THIS.parents[1] / "notify"))  # local/scripts/notify (ops.metrics_push)

import config  # noqa: E402
from fastembed import TextEmbedding  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import (  # noqa: E402
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

import brain_page  # noqa: E402
import brain_bus  # noqa: E402
import memory_core as core  # noqa: E402
from security import injection_guard  # noqa: E402

try:
    from ops import metrics_push  # noqa: E402
except Exception:  # metrics are best-effort
    metrics_push = None

MEMORY_COLLECTION = os.getenv("MEMORY_COLLECTION", "agent_memory")
# Personal (scope=user) memory lives in a SEPARATE local-only collection from shared
# (scope=shared) memory — two Qdrant collections on the same local instance, not two
# machines. Keeping them separate means a bulk operation on one never touches the other.
USER_COLLECTION = os.getenv("MEMORY_USER_COLLECTION", "agent_memory_user")
MEMORY_PORT = int(os.getenv("MEMORY_SERVICE_PORT", "7800"))
# Loopback only: the memory holds what the owner told the agent, and nothing else needs to reach it.
MEMORY_HOST = os.getenv("MEMORY_SERVICE_HOST", "127.0.0.1")
HEARTBEAT_SECONDS = int(os.getenv("MEMORY_HEARTBEAT_SECONDS", "60"))
VECTOR_DIM = 384
SCOPES = {"shared", "user"}
# Dense candidates per collection, as a multiple of k: room for the fusion and for skipping
# replaced memories.
DENSE_CANDIDATE_FACTOR = 4
SCROLL_PAGE = 512
# The session-start brief: about what Hermes keeps in MEMORY.md and USER.md together.
BRIEF_MAX_CHARS = int(os.getenv("MEMORY_BRIEF_MAX_CHARS", "3500"))
# Consolidation: two live memories this similar say the same thing; the older one is replaced.
CONSOLIDATE_THRESHOLD = 0.95
CONSOLIDATE_NEIGHBORS = 3
# How the dense and the lexical rankings merge: "convex" (normalized scores, FUSION_ALPHA for the
# dense side) or "rrf". The default is the one evals/memory_benchmark.py chose on its dev split.
FUSION = os.getenv("MEMORY_FUSION", "convex")
FUSION_ALPHA = float(os.getenv("MEMORY_FUSION_ALPHA", "0.7"))
# With "adaptive": a query term held by at most this many memories gets RARE_TERM_ALPHA instead.
RARE_TERM_MAX_DOCS = 2
RARE_TERM_ALPHA = 0.3

# --- Auth: identity is derived from the TOKEN, never from a client-supplied field ---
# MEMORY_USER_TOKENS maps each user's token to their identity: "tok_juan:juan,tok_maria:maria".
# MEMORY_ADMIN_TOKEN may act for any user and delete shared memory.
# MEMORY_ALLOW_NO_AUTH=true disables auth for LOCAL-ONLY use (trusts the client identity).
ALLOW_NO_AUTH = os.getenv("MEMORY_ALLOW_NO_AUTH", "false").lower() in ("1", "true", "yes")
MEMORY_ADMIN_TOKEN = os.getenv("MEMORY_ADMIN_TOKEN", "")


def _parse_user_tokens(raw: str) -> dict:
    mapping = {}
    for pair in raw.split(","):
        pair = pair.strip()
        if ":" in pair:
            tok, user = pair.split(":", 1)
            if tok.strip() and user.strip():
                mapping[tok.strip()] = user.strip()
    return mapping


USER_TOKENS = _parse_user_tokens(os.getenv("MEMORY_USER_TOKENS", ""))

# Fail CLOSED: never run wide-open by accident. Require configured auth unless
# no-auth is explicitly opted into (local dev only).
if not ALLOW_NO_AUTH and not USER_TOKENS and not MEMORY_ADMIN_TOKEN:
    raise RuntimeError(
        "No auth configured: set MEMORY_USER_TOKENS (and/or MEMORY_ADMIN_TOKEN), "
        "or MEMORY_ALLOW_NO_AUTH=true for local-only use."
    )


@asynccontextmanager
async def lifespan(app):
    # Heartbeat: push metrics on a timer so the board's liveness panel reflects
    # "service up", not just "last add/search". Without it an idle-but-healthy
    # service would drift to red. The blocking push runs off the event loop.
    loop = asyncio.get_event_loop()
    _push_metrics()  # immediate, so the panel is green from boot

    async def beat():
        while True:
            await asyncio.sleep(HEARTBEAT_SECONDS)
            await loop.run_in_executor(None, _push_metrics)

    task = loop.create_task(beat())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="agent-memory", lifespan=lifespan)
_model = None
_client = None
# Counters since service start (pushed as gauges; reset on restart). The real
# persistent state is memory_entries, read live from Qdrant on every push.
_counters = {"writes": 0.0, "searches": 0.0, "hits": 0.0}


def _embed_model():
    global _model
    if _model is None:
        _model = TextEmbedding(
            model_name=config.EMBEDDING_MODEL,
            cache_dir=str(THIS.parent / ".cache" / "fastembed"),
        )
    return _model


def _embed(text: str):
    return list(_embed_model().embed([text]))[0].tolist()


def _client_get() -> QdrantClient:
    global _client
    if _client is None:
        # Pass https explicitly (False by default). qdrant-client auto-enables TLS when an
        # api_key is set, which fails against a plain-HTTP qdrant (SSL WRONG_VERSION_NUMBER).
        kwargs = {
            "host": config.QDRANT_HOST,
            "port": config.QDRANT_PORT,
            "timeout": 5,
            "https": config.QDRANT_HTTPS,
        }
        if config.QDRANT_API_KEY:
            kwargs["api_key"] = config.QDRANT_API_KEY
        client = QdrantClient(**kwargs)
        for coll in (MEMORY_COLLECTION, USER_COLLECTION):
            if not client.collection_exists(coll):
                client.create_collection(
                    collection_name=coll,
                    vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
                )
        _client = client
    return _client


def _collection_for(scope: str) -> str:
    """Shared → agent_memory (local, shared across callers); user → local-only USER_COLLECTION."""
    return USER_COLLECTION if scope == "user" else MEMORY_COLLECTION


def _resolve(token: str, claimed_user: str = ""):
    """Return (verified_user, is_admin); raise 401 on bad auth.

    Identity comes from the token, NOT from any client-supplied field, so a
    caller cannot read or write as another user by spoofing it. In no-auth
    local mode the client-supplied user is trusted (testing only).
    """
    token = token or ""
    if MEMORY_ADMIN_TOKEN and secrets.compare_digest(token, MEMORY_ADMIN_TOKEN):
        return claimed_user, True
    for tok, user in USER_TOKENS.items():
        if secrets.compare_digest(token, tok):
            return user, False
    if ALLOW_NO_AUTH and not USER_TOKENS and not MEMORY_ADMIN_TOKEN:
        return claimed_user, True
    raise HTTPException(status_code=401, detail="invalid memory token")


def _push_metrics():
    if not metrics_push:
        return
    try:
        client = _client_get()
        # Persistent state: live entry counts per scope, straight from Qdrant.
        for scope in SCOPES:
            n = client.count(
                _collection_for(scope),
                count_filter=Filter(
                    must=[FieldCondition(key="scope", match=MatchValue(value=scope))]
                ),
            ).count
            metrics_push.push_run(
                "memory", extra_grouping={"scope": scope}, memory_entries=float(n)
            )
        # Activity counters since service start (no scope label).
        hits, searches = _counters["hits"], _counters["searches"]
        metrics_push.push_run(
            "memory",
            memory_writes_total=_counters["writes"],
            memory_searches_total=searches,
            memory_search_hits_total=hits,
            memory_hit_rate=(hits / searches if searches else 0.0),
        )
    except Exception:
        pass


class AddReq(BaseModel):
    text: str
    scope: str = "user"
    user: str = ""
    category: str = core.DEFAULT_CATEGORY
    source: str = "stated"  # stated | inferred
    # A fact that changes over time (my laptop, the staging port): the newest one with the same
    # key replaces the others, which stay as history.
    state_key: str = ""


def _owner(scope: str, user: str) -> FieldCondition:
    """What a caller may read: all shared memory, and only their own user memory."""
    if scope == "shared":
        return FieldCondition(key="scope", match=MatchValue(value="shared"))
    return FieldCondition(key="user", match=MatchValue(value=user))


def _visible_filter(scope: str, user: str) -> Filter:
    return Filter(must=[_owner(scope, user)])


def _visible(user: str) -> list[tuple[str, Filter]]:
    return [
        (MEMORY_COLLECTION, _visible_filter("shared", user)),
        (USER_COLLECTION, _visible_filter("user", user)),
    ]


def _scroll_all(collection: str, query_filter: Filter, with_vectors: bool = False) -> list:
    """Every point a filter selects, page by page."""
    points, offset = [], None
    while True:
        page, offset = _client_get().scroll(
            collection_name=collection,
            scroll_filter=query_filter,
            limit=SCROLL_PAGE,
            offset=offset,
            with_payload=True,
            with_vectors=with_vectors,
        )
        points.extend(page)
        if offset is None:
            return points


def _supersede(collection: str, scope: str, user: str, state_key: str, new_id: str) -> int:
    """Mark the live memories with this key as replaced by `new_id`. Returns how many."""
    key_filter = Filter(
        must=[
            _owner(scope, user),
            FieldCondition(key="state_key", match=MatchValue(value=state_key)),
        ]
    )
    old = [p for p in _scroll_all(collection, key_filter) if str(p.id) != new_id]
    old = [p for p in old if core.is_live(p.payload or {})]
    if old:
        _client_get().set_payload(
            collection_name=collection,
            payload={"superseded_by": new_id, "valid_until": time.time()},
            points=[p.id for p in old],
        )
    return len(old)


def _public(point_id, payload: dict, score: float | None = None) -> dict:
    out = {"id": str(point_id), **payload, "category": core.category_of(payload.get("category"))}
    if score is not None:
        out["score"] = round(score, 4)
    return out


@app.post("/memory/add")
def add(req: AddReq, x_memory_token: str = Header("")):
    verified_user, _ = _resolve(x_memory_token, req.user)
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="empty text")
    # A memory comes back into every later session: an injection stored here would outlive the
    # session that wrote it. A block is refused; a warning is stored with its signals.
    guard = injection_guard.scan(req.text, source="memory")
    if guard.verdict is injection_guard.Verdict.BLOCK:
        raise HTTPException(
            status_code=422,
            detail={"reason": "injection signals", "signals": guard.signals},
        )
    scope = req.scope if req.scope in SCOPES else "user"
    # Identity from the token: a caller can only write user-scoped memory as themselves.
    user = verified_user if scope == "user" else ""
    # Deterministic id → re-adding the same memory updates, never duplicates.
    mid = str(uuid.UUID(bytes=hashlib.sha256(f"{scope}:{user}:{req.text}".encode()).digest()[:16]))
    payload = {
        "text": req.text,
        "scope": scope,
        "user": user,
        "category": core.category_of(req.category),
        "source": req.source if req.source in ("stated", "inferred") else "stated",
        "created_at": time.time(),
    }
    if guard.signals:
        payload["flags"] = guard.signals
    collection = _collection_for(scope)
    state_key = req.state_key.strip()
    replaced = 0
    if state_key:
        payload["state_key"] = state_key
        replaced = _supersede(collection, scope, user, state_key, mid)
    _client_get().upsert(
        collection_name=collection,
        points=[PointStruct(id=mid, vector=_embed(req.text), payload=payload)],
    )
    _counters["writes"] += 1
    _push_metrics()
    # the brain page: encoding, on the left. What was saved stays out of the bus
    kept = f"{payload['category']} · {scope}"
    brain_bus.emit("memory", f"memory saved · {kept}", ["hip", "atl"], side="L")
    return {"id": mid, **payload, "replaced": replaced}


@app.get("/memory/search")
def search(
    q: str,
    user: str = "",
    k: int = 5,
    include_history: bool = False,
    x_memory_token: str = Header(""),
):
    """Hybrid search: the dense ranking and the BM25 ranking, fused. Replaced memories are left
    out unless include_history asks for them. Filters use the VERIFIED identity, never the raw
    query parameter: no cross-user reads."""
    verified_user, _ = _resolve(x_memory_token, user)
    vec = _embed(q)
    client = _client_get()
    by_id: dict[str, tuple] = {}
    dense: list[tuple[str, float]] = []
    docs: list[tuple[str, str]] = []
    for collection, visible in _visible(verified_user):
        for p in client.query_points(
            collection_name=collection,
            query=vec,
            limit=k * DENSE_CANDIDATE_FACTOR,
            query_filter=visible,
            with_payload=True,
        ).points:
            if include_history or core.is_live(p.payload or {}):
                by_id[str(p.id)] = (p.id, p.payload or {})
                dense.append((str(p.id), p.score))
        for p in _scroll_all(collection, visible):
            if include_history or core.is_live(p.payload or {}):
                by_id[str(p.id)] = (p.id, p.payload or {})
                docs.append((str(p.id), (p.payload or {}).get("text", "")))
    index = core.BM25Index(docs)
    if FUSION == "rrf":
        dense_ranking = [doc_id for doc_id, _ in sorted(dense, key=lambda d: -d[1])]
        fused = core.rrf([dense_ranking, index.ranked(q, k * DENSE_CANDIDATE_FACTOR)])[:k]
    else:
        alpha = FUSION_ALPHA
        # "adaptive": a query that names something only a few memories hold is a lookup
        if FUSION == "adaptive" and index.has_rare_term(q, RARE_TERM_MAX_DOCS):
            alpha = RARE_TERM_ALPHA
        fused = core.convex(dict(dense), index.scores(q), alpha)[:k]
    _counters["searches"] += 1
    if fused:
        _counters["hits"] += 1
    _push_metrics()
    # the brain page: retrieval, on the right. The query is shown masked
    asked = brain_bus.mask(q)
    brain_bus.emit(
        "recall", f"memory search · {asked} · {len(fused)} found", ["atl", "hip"], side="R"
    )
    return {"results": [_public(*by_id[doc_id], score=score) for doc_id, score in fused]}


@app.post("/memory/consolidate")
def consolidate(threshold: float = CONSOLIDATE_THRESHOLD, x_memory_token: str = Header("")):
    """The nightly pass: a live memory that says the same as a newer one is marked replaced by it.
    Nothing is deleted. Shared memory is only consolidated with the admin token."""
    verified_user, is_admin = _resolve(x_memory_token)
    client = _client_get()
    merged: list[dict] = []
    for collection, visible in _visible(verified_user):
        if collection == MEMORY_COLLECTION and not is_admin:
            continue
        live = [
            p
            for p in _scroll_all(collection, visible, with_vectors=True)
            if core.is_live(p.payload or {})
        ]
        done: set[str] = set()
        for point in sorted(live, key=lambda p: -(p.payload or {}).get("created_at", 0)):
            if str(point.id) in done:
                continue
            for near in client.query_points(
                collection_name=collection,
                query=point.vector,
                limit=CONSOLIDATE_NEIGHBORS + 1,
                query_filter=visible,
                score_threshold=threshold,
                with_payload=True,
            ).points:
                payload = near.payload or {}
                older = payload.get("created_at", 0) < (point.payload or {}).get("created_at", 0)
                if str(near.id) == str(point.id) or not older or not core.is_live(payload):
                    continue
                if str(near.id) in done:
                    continue
                client.set_payload(
                    collection_name=collection,
                    payload={"superseded_by": str(point.id), "valid_until": time.time()},
                    points=[near.id],
                )
                done.add(str(near.id))
                merged.append({"replaced": str(near.id), "by": str(point.id)})
    brain_page.note_night(len(merged))  # the brain page: the evidence of the night cycle
    return {"merged": len(merged), "pairs": merged}


@app.get("/memory/brief")
def memory_brief(
    user: str = "", max_chars: int = BRIEF_MAX_CHARS, x_memory_token: str = Header("")
):
    """What a session starts with: the live memories that fit the budget, most important first.
    A memory with injection signals never reaches a session start, whatever was stored."""
    verified_user, _ = _resolve(x_memory_token, user)
    memories = []
    for collection, visible in _visible(verified_user):
        for p in _scroll_all(collection, visible):
            payload = p.payload or {}
            if injection_guard.scan(payload.get("text", ""), source="memory").is_clean:
                memories.append(_public(p.id, payload))
    chosen = core.brief(memories, max_chars)
    return {"memories": chosen, "chars": sum(len(m["text"]) + 3 for m in chosen)}


class ForgetReq(BaseModel):
    id: str


@app.post("/memory/forget")
def forget(req: ForgetReq, x_memory_token: str = Header("")):
    verified_user, is_admin = _resolve(x_memory_token)
    client = _client_get()
    coll, found = None, None
    for c in (MEMORY_COLLECTION, USER_COLLECTION):
        hit = client.retrieve(c, ids=[req.id], with_payload=True)
        if hit:
            coll, found = c, hit
            break
    if not found:
        raise HTTPException(status_code=404, detail="memory not found")
    payload = found[0].payload or {}
    # Ownership check: only delete your own user-memory; shared needs admin.
    if payload.get("scope") == "shared" and not is_admin:
        raise HTTPException(status_code=403, detail="shared memory requires admin")
    if payload.get("scope") == "user" and not is_admin and payload.get("user") != verified_user:
        raise HTTPException(status_code=403, detail="not your memory")
    client.delete(collection_name=coll, points_selector=[req.id])
    _push_metrics()
    brain_bus.emit("forget", "memory forgotten", ["vta"])
    return {"forgotten": req.id}


@app.get("/memory/whoami")
def whoami(x_memory_token: str = Header("")):
    """Who this token is here; 401 when the service does not know it. /memory/health answers
    anyone, so on a machine with two kits it cannot tell a kit that the service on its address
    is its own: accepting the kit's token does. Touches no memory."""
    verified_user, is_admin = _resolve(x_memory_token)
    return {"user": verified_user, "admin": is_admin}


@app.get("/memory/health")
def health():
    try:
        client = _client_get()
        return {
            "status": "ok",
            "collection": MEMORY_COLLECTION,
            "entries": client.count(MEMORY_COLLECTION).count,
            "user_collection": USER_COLLECTION,
            "user_entries": client.count(USER_COLLECTION).count,
        }
    except Exception as e:
        return {"status": "degraded", "error": str(e)[:160]}


brain_page.mount(app, health)  # the brain page: /brain and /api/brain/*


if __name__ == "__main__":
    uvicorn.run(app, host=MEMORY_HOST, port=MEMORY_PORT, log_level="warning")
