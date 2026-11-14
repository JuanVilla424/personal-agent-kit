#!/usr/bin/env python3
"""bin/brain_backup.py — local backups of the Qdrant brain, with generations.

Why: the memory is the kit's only state that exists nowhere else (docs live in git,
lessons in bin/lessons.py). If the machine dies, the brain dies with it. This takes
Qdrant collection snapshots, stores them under ``~/.pak/backups/brain`` with generation
marks, keeps the last N per collection, and restores one back with a FULL replace —
the same semantics the snapshot/restore pair of the father kit uses for its replicas.

Commands (reached as ``pak brain …`` from bin/pak_cli.py):

  backup  [--keep N]                    snapshot every collection, prune old generations
  list                                  show the stored snapshots and their generations
  restore [id|latest] [--collection C] [--yes]
                                        upload a stored snapshot back (FULL REPLACE — it
                                        never merges). ``--yes`` is required: this
                                        overwrites the live collection.
  prune [--keep N]                      drop generations beyond the last N per collection

Collections: ``$MEMORY_BACKUP_COLLECTIONS`` (comma separated) defaults to the kit's
three — MEMORY_COLLECTION (agent_memory), MEMORY_USER_COLLECTION (agent_memory_user)
and QDRANT_COLLECTION (runbooks), read from the root .env like every other component.
"""

import argparse
import fcntl
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "local" / "scripts" / "memory_index"))

import config  # noqa: E402  (memory_index config: loads the root .env once)

DEFAULT_KEEP = 5
LOCK_TIMEOUT_S = 5
REQUEST_TIMEOUT_S = 30
GENERATION_PREFIX = "latest"


def root() -> Path:
    """Where the brain backups live (``$PAK_BACKUP_ROOT`` or ~/.pak/backups/brain)."""
    return Path(os.environ.get("PAK_BACKUP_ROOT") or Path.home() / ".pak" / "backups" / "brain")


def collections() -> list[str]:
    """The collections worth backing up, in the order they should be restored."""
    custom = os.environ.get("MEMORY_BACKUP_COLLECTIONS", "")
    if custom.strip():
        return [c.strip() for c in custom.split(",") if c.strip()]
    memory = os.getenv("MEMORY_COLLECTION", "agent_memory")
    user = os.getenv("MEMORY_USER_COLLECTION", "agent_memory_user")
    seen: list[str] = []
    for coll in (memory, user, config.QDRANT_COLLECTION):
        if coll not in seen:
            seen.append(coll)
    return seen


def base_url() -> str:
    scheme = (
        "https" if os.getenv("QDRANT_HTTPS", "false").lower() in ("1", "true", "yes") else "http"
    )
    host = os.getenv("QDRANT_HOST", config.QDRANT_HOST)
    port = os.getenv("QDRANT_PORT", str(config.QDRANT_PORT))
    return f"{scheme}://{host}:{port}"


def _headers() -> dict[str, str]:
    key = os.getenv("QDRANT_API_KEY", config.QDRANT_API_KEY)
    return {"api-key": key} if key else {}


def _request(
    method: str, url: str, data: bytes | None = None, timeout: int = REQUEST_TIMEOUT_S
) -> tuple[int, bytes]:
    """One HTTP call that never raises for 4xx/5xx: callers decide on the status."""
    req = urllib.request.Request(url, data=data, method=method, headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _multipart(path: Path) -> tuple[str, bytes]:
    """A minimal multipart/form-data body with the snapshot file as the ``snapshot`` field."""
    boundary = "----pak-brain-backup-boundary"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="snapshot"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return f"multipart/form-data; boundary={boundary}", head + path.read_bytes() + tail


def _create_snapshot(coll: str) -> str | None:
    """Ask Qdrant for a snapshot of one collection; its name, or None on failure."""
    status, body = _request("POST", f"{base_url()}/collections/{coll}/snapshots")
    if status != 200:
        return None
    try:
        return json.loads(body.decode("utf-8"))["result"]["name"]
    except (KeyError, ValueError):
        return None


def _download_snapshot(coll: str, name: str, dest: Path) -> bool:
    status, body = _request("GET", f"{base_url()}/collections/{coll}/snapshots/{name}", timeout=120)
    if status != 200 or not body:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return True


def _delete_remote_snapshot(coll: str, name: str) -> None:
    # Qdrant keeps the working copy: the canonical one is ours on disk, like the father kit.
    _request("DELETE", f"{base_url()}/collections/{coll}/snapshots/{name}")


def _upload_snapshot(coll: str, path: Path) -> tuple[int, bytes]:
    content_type, body = _multipart(path)
    url = f"{base_url()}/collections/{coll}/snapshots/upload?priority=snapshot"
    return _request("POST", url, data=body, timeout=120)


def _lock() -> int | None:
    """Serialize backup and restore: two overlapping writes would corrupt a generation."""
    root().mkdir(parents=True, exist_ok=True)
    handle = os.open(str(root() / ".lock"), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(handle)
        return None
    return handle


def _store(coll: str, body: bytes) -> Path:
    digest = hashlib.sha256(body).hexdigest()[:12]
    stamp = int(time.time())
    dest = root() / coll / f"{stamp}-{digest}.snapshot"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    (root() / f"{GENERATION_PREFIX}.{coll}.generation").write_text(dest.name + "\n")
    return dest


def _prune(coll: str, keep: int) -> int:
    """Drop generations beyond the last ``keep`` of one collection; returns how many fell."""
    keep = max(0, keep)
    # By mtime, never by name: within the same second the name sorts by hash, and the
    # hash of the just-stored snapshot can sort before the older ones.
    files = sorted((root() / coll).glob("*.snapshot"), key=lambda p: p.stat().st_mtime)
    dropped = 0
    for old in files[:-keep] if keep else files:
        old.unlink()
        dropped += 1
    return dropped


def take(keep: int = DEFAULT_KEEP) -> int:
    """Snapshot every collection, store it with a generation mark and prune old ones."""
    handle = _lock()
    if handle is None:
        print("backup: another run is in progress — skipping")
        return 0
    failed = False
    try:
        for coll in collections():
            name = _create_snapshot(coll)
            if not name:
                print(f"✘ {coll}: snapshot creation failed", file=sys.stderr)
                failed = True
                continue
            dest = root() / coll / "incoming.snapshot"
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not _download_snapshot(coll, name, dest):
                print(f"✘ {coll}: snapshot download came back empty", file=sys.stderr)
                failed = True
                continue
            stored = _store(coll, dest.read_bytes())
            dest.unlink()
            _delete_remote_snapshot(coll, name)
            dropped = _prune(coll, keep)
            suffix = f", pruned {dropped}" if dropped else ""
            print(f"✔ {coll}: {stored.name} ({stored.stat().st_size / 1024:.0f} KiB{suffix})")
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)
    return 1 if failed else 0


def list_backups() -> int:
    """Print every stored generation, oldest first, per collection."""
    found = False
    for coll in sorted(p.name for p in root().iterdir() if p.is_dir()) if root().is_dir() else []:
        for path in sorted((root() / coll).glob("*.snapshot")):
            found = True
            age_h = (time.time() - path.stat().st_mtime) / 3600
            print(
                f"{coll:22} {path.name}  {path.stat().st_size / 1024:8.0f} KiB  {age_h:6.1f}h ago"
            )
    if not found:
        print(f"no brain backups yet in {root()} — pak brain backup")
        return 1
    return 0


def restore(target: str = "latest", coll: str | None = None, yes: bool = False) -> int:
    """Upload a stored snapshot back into its collection. FULL REPLACE of the collection."""
    wanted = [coll] if coll else collections()
    if coll and coll not in collections():
        print(
            f"restore: '{coll}' is not one of the backed-up collections: {collections()}",
            file=sys.stderr,
        )
        return 2
    if not yes:
        print(
            "restore: this FULL-REPLACEs the live collection. Re-run with --yes to confirm.",
            file=sys.stderr,
        )
        return 2
    failed = False
    for name in wanted:
        gen = root() / f"{GENERATION_PREFIX}.{name}.generation"
        if target == "latest":
            if not gen.exists():
                print(f"✘ {name}: no generation mark yet — pak brain backup first", file=sys.stderr)
                failed = True
                continue
            snapshot = root() / name / gen.read_text().strip()
        else:
            snapshot = root() / name / target
        if not snapshot.exists():
            print(
                f"✘ {name}: snapshot '{snapshot.name}' not found in {root() / name}",
                file=sys.stderr,
            )
            failed = True
            continue
        status, body = _upload_snapshot(name, snapshot)
        if status != 200:
            print(
                f"✘ {name}: restore upload failed (HTTP {status}): {body[:200]!r}", file=sys.stderr
            )
            failed = True
            continue
        print(f"✔ {name}: restored from {snapshot.name} (full replace)")
    return 1 if failed else 0


def prune(keep: int = DEFAULT_KEEP) -> int:
    """Drop generations beyond the last ``keep`` of every collection."""
    dropped = 0
    for coll in collections():
        dropped += _prune(coll, keep)
    print(f"prune: {dropped} old generation(s) dropped, keeping {keep} per collection")
    return 0


def latest_age_hours(coll: str | None = None) -> float | None:
    """Hours since the newest generation mark; None when there is none (doctor's off state)."""
    colls = [coll] if coll else collections()
    ages = []
    for name in colls:
        gen = root() / f"{GENERATION_PREFIX}.{name}.generation"
        if gen.exists():
            file = root() / name / gen.read_text().strip()
            if file.exists():
                ages.append((time.time() - file.stat().st_mtime) / 3600)
    return min(ages) if ages else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pak brain", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_take = sub.add_parser("backup", help="snapshot every collection and prune old generations")
    p_take.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    sub.add_parser("list", help="show the stored snapshots")
    p_res = sub.add_parser("restore", help="upload a stored snapshot back (FULL REPLACE)")
    p_res.add_argument("target", nargs="?", default="latest", help="snapshot id, or 'latest'")
    p_res.add_argument("--collection", default=None)
    p_res.add_argument("--yes", action="store_true", help="confirm the full replace")
    p_prune = sub.add_parser("prune", help="drop generations beyond the last N per collection")
    p_prune.add_argument("--keep", type=int, default=DEFAULT_KEEP)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if args.command == "backup":
        return take(keep=args.keep)
    if args.command == "list":
        return list_backups()
    if args.command == "restore":
        return restore(target=args.target, coll=args.collection, yes=args.yes)
    return prune(keep=args.keep)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
