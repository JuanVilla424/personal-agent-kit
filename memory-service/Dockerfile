# agent-memory-service — the local agent-memory API and the SINGLE writer of
# the `agent_memory` Qdrant collection. FastAPI + uvicorn on :7800, server-side
# embedding via fastembed (384-dim). Optional: run this as a long-running container
# if you'd rather isolate it than run it as a plain local process (see the repo README).
#
# Build (context = repo ROOT, not this folder):
#   docker build -f memory-service/Dockerfile -t agent-memory-service:latest .
#
# Runtime config (env vars / your own secret store). The service is FAIL-CLOSED: it
# refuses to start without auth, so these must be provided at deploy time:
#   QDRANT_HOST=<your qdrant host>   QDRANT_PORT=6337
#   MEMORY_USER_TOKENS="tok:user,..."         (and/or MEMORY_ADMIN_TOKEN)
FROM python:3.12-slim@sha256:6c4dd321d176d61ea848dc8c73a4f7dbae8f70e0ee48bb411ea2f045b599fa8e

# Standard practice: never run as root.
RUN useradd -m -r usrapp

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MEMORY_SERVICE_PORT=7800 \
    EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

WORKDIR /app

# Dependencies — single source of truth is the memory_index requirements.
COPY local/scripts/memory_index/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Service code, preserving the on-disk layout the code resolves by path:
#   config.py        -> REPO_ROOT = parents[3]  (needs the local/scripts/memory_index nesting)
#   memory_service.py-> imports `ops` from the sibling local/scripts/notify
COPY local/scripts/memory_index/ /app/local/scripts/memory_index/
COPY local/scripts/notify/ops/   /app/local/scripts/notify/ops/

# Bake the embedding model into the image (offline + fast cold start). The cache dir
# MUST match memory_service._embed_model(): <memory_index>/.cache/fastembed.
RUN python -c "from fastembed import TextEmbedding; TextEmbedding(model_name='${EMBEDDING_MODEL}', cache_dir='/app/local/scripts/memory_index/.cache/fastembed')"

RUN chown -R usrapp:usrapp /app
USER usrapp

EXPOSE 7800
CMD ["python", "/app/local/scripts/memory_index/memory_service.py"]
