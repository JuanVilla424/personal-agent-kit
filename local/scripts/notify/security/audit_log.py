import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path

log = logging.getLogger("audit")

_AUDIT_DIR = Path(__file__).parent.parent / "audit"
_lock = asyncio.Lock()
_prev_hash: dict[str, str] = {}


def _date_key() -> str:
    import datetime

    return datetime.date.today().isoformat()


def _log_path() -> Path:
    _AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    return _AUDIT_DIR / f"{_date_key()}.jsonl"


async def write(event: str, **kwargs) -> None:
    date_key = _date_key()
    entry: dict = {
        "ts": time.time(),
        "event": event,
        **kwargs,
    }
    # Strip None values
    entry = {k: v for k, v in entry.items() if v is not None}

    async with _lock:
        prev = _prev_hash.get(date_key, "0" * 64)
        payload = json.dumps({k: v for k, v in entry.items()}, sort_keys=True, ensure_ascii=False)
        entry_hash = hashlib.sha256((prev + payload).encode()).hexdigest()
        entry["prev_hash"] = prev
        entry["hash"] = entry_hash
        _prev_hash[date_key] = entry_hash

        path = _log_path()
        line = json.dumps(entry, ensure_ascii=False) + "\n"
        try:
            path.chmod(0o640) if path.exists() else None
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            path.chmod(0o440)
        except Exception as e:
            log.error("Audit write failed: %s", e)


def verify_chain(date_str: str | None = None) -> bool:
    if not date_str:
        date_str = _date_key()
    path = _AUDIT_DIR / f"{date_str}.jsonl"
    if not path.exists():
        return True
    prev = "0" * 64
    with path.open() as f:
        for line_raw in f:
            line_raw = line_raw.strip()
            if not line_raw:
                continue
            try:
                entry = json.loads(line_raw)
            except json.JSONDecodeError:
                return False
            stored_hash = entry.pop("hash", None)
            stored_prev = entry.pop("prev_hash", None)
            if stored_prev != prev:
                return False
            payload = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            expected = hashlib.sha256((prev + payload).encode()).hexdigest()
            if stored_hash != expected:
                return False
            prev = stored_hash
    return True


if __name__ == "__main__":
    import sys

    date_arg = sys.argv[1] if len(sys.argv) > 1 else None
    ok = verify_chain(date_arg)
    print("OK" if ok else "TAMPERED")
    sys.exit(0 if ok else 1)
