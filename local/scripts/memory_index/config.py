import os
from pathlib import Path
from dotenv import load_dotenv

# Single config in the root .env ("everything in one .env" model). override=False →
# the value set on the CLI always wins. Root resolved from __file__
# (cwd-independent): this file lives in local/scripts/memory_index/ → parents[3].
REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env", override=False)

QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "7733"))
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "runbooks")
# Optional remote Qdrant: api key + TLS. Empty / false → local Qdrant on 127.0.0.1 (no auth).
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HTTPS = os.getenv("QDRANT_HTTPS", "false").lower() in ("1", "true", "yes")
EMBEDDING_MODEL = os.getenv(
    "EMBEDDING_MODEL",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
SCORE_THRESHOLD = float(os.getenv("SCORE_THRESHOLD", "0.55"))
TOP_K = int(os.getenv("TOP_K", "5"))

# Docs root: three levels up from this file (local/scripts/memory_index/ → repo root) + docs/
DOCS_ROOT = os.getenv(
    "DOCS_ROOT",
    str(Path(__file__).parent.parent.parent.parent / "docs"),
)
