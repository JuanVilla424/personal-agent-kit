# 🧠 Memory Index — Semantic Search for Runbooks

![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)
![Qdrant](https://img.shields.io/badge/Qdrant-v1.18-orange.svg)
![Status](https://img.shields.io/badge/Status-Active-green.svg)
![Model](https://img.shields.io/badge/Embeddings-multilingual--MiniLM--L12--v2-purple.svg)

Semantic vector search over the troubleshooting runbooks. Any agent can use this to query by
symptom description before falling back to a manual read of the docs.

---

## 🏗️ Architecture

```
docs/TROUBLESHOOTING.md         ──┐──► Chunker ──► fastembed (multilingual-e5-small)
docs/SETUP-TROUBLESHOOTING.md   ──┘                     │
                                                         ▼
                                              Qdrant :7733 (local Docker)
                                                         │
                                                query → top-K results
```

- **Embeddings**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` via `fastembed` (ONNX, offline, ~220 MB cache, 50 languages).
- **Vector store**: Qdrant running in Docker on port `7733` (REST) / `7734` (gRPC).
- **Chunking**: splits docs by `##` / `###` markdown headers; each chunk ≤ 2000 chars.
- **IDs**: deterministic SHA-256 → UUID per `source::section` pair — re-indexing is idempotent.

> **Note on Docker user:** Qdrant runs as its official container image without a custom
> non-root user. The `usrapp` standard applies to images this project builds (custom Dockerfiles).
> This is a stock backend service.

---

## 🚀 Getting Started

### 1. Start Qdrant

```bash
docker compose -f local/scripts/memory_index/docker-compose.yml up -d
```

Qdrant REST API will be available at `http://localhost:7733`.

### 2. Install dependencies

```bash
.venv/bin/pip install -r local/scripts/memory_index/requirements.txt
```

`fastembed` will download `multilingual-e5-small` (~120 MB) on first run into
`local/scripts/memory_index/.cache/fastembed/`.

### 3. Index documents

```bash
.venv/bin/python local/scripts/memory_index/main.py index
```

### 4. Query

```bash
# Human-readable output
.venv/bin/python local/scripts/memory_index/main.py query "login returns 500 and the database is saturated"

# JSON output (for scripting)
.venv/bin/python local/scripts/memory_index/main.py query "login 500" --json
```

---

## ⚙️ Configuration

Copy `.env.example` to `.env` to override defaults:

| Variable            | Default                                                       | Description                         |
| ------------------- | ------------------------------------------------------------- | ----------------------------------- |
| `QDRANT_HOST`       | `localhost`                                                   | Qdrant host                         |
| `QDRANT_PORT`       | `7733`                                                        | Qdrant REST port                    |
| `QDRANT_COLLECTION` | `runbooks`                                                    | Collection name                     |
| `EMBEDDING_MODEL`   | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` | fastembed model                     |
| `DOCS_ROOT`         | auto-detected                                                 | Absolute path to `docs/`            |
| `SCORE_THRESHOLD`   | `0.55`                                                        | Minimum cosine similarity to return |
| `TOP_K`             | `5`                                                           | Maximum results per query           |

---

## 🔄 Re-indexing

Run `index` again after adding a new lesson learned — it is idempotent (upsert by stable ID):

```bash
.venv/bin/python local/scripts/memory_index/main.py index
```

---

## 🛑 Graceful degradation

If Qdrant is not running, `query` exits 0 and logs a warning so the caller can fall back to a
manual read of the docs without blocking.
