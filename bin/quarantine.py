#!/usr/bin/env python3
"""quarantine.py — the agent's ONLY way to remove something: a reversible move.

Deleting is a human act: the guard blocks rm and every other delete (bin/auto_guard.py, rule
rm_any and its kin, plus the Stage 2 veto). When a task needs something out of its place (scratch
files, an obsolete draft), the agent MOVES it here instead. Each file lands under the quarantine
root with a sha256 manifest that is checked after the move (read again and compared, never
assumed), so the human can restore it or delete it for real later.

Retention: `prune --days N` is the human's or a timer's job. The agent never prunes: pruning is a
delete.

Usage:
  bin/quarantine.py mv PATH [PATH ...]     # move paths into a new quarantine batch
  bin/quarantine.py show [BATCH_ID]        # list batches / show one manifest
  bin/quarantine.py prune --days 30 --yes  # human or timer only: drop batches older than N days

The root is ~/.pak/quarantine, or QUARANTINE_ROOT when set.

Exit codes: 0 ok · 2 refused (safety) · 3 path missing · 4 verification failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path("~/.pak/quarantine").expanduser()
# Never quarantine whole top-level trees, the home itself, or anything that CONTAINS the quarantine
# root or the home (moving an ancestor would swallow the destination).
_SYSTEM_TOP = {
    "/bin",
    "/boot",
    "/dev",
    "/etc",
    "/lib",
    "/lib64",
    "/media",
    "/mnt",
    "/opt",
    "/proc",
    "/root",
    "/run",
    "/sbin",
    "/srv",
    "/sys",
    "/tmp",
    "/usr",
    "/var",
}
SECONDS_PER_DAY = 86400


def _root() -> Path:
    return Path(os.environ.get("QUARANTINE_ROOT", str(DEFAULT_ROOT))).expanduser()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _files_under(path: Path) -> list[Path]:
    if path.is_file() or path.is_symlink():
        return [path]
    return sorted(p for p in path.rglob("*") if p.is_file() and not p.is_symlink())


def _refusal(path: Path, root: Path) -> str | None:
    """Why this path may NOT be quarantined, or None if it may."""
    resolved = Path(os.path.realpath(path))
    home = Path("~").expanduser()
    if str(resolved) == "/":
        return "refusing to quarantine / itself"
    # The home itself or an ancestor of it would swallow the destination; files under it are the
    # normal case.
    if resolved == home or resolved in home.parents:
        return f"refusing to quarantine the home tree itself ({home} or an ancestor)"
    if resolved == root or resolved in root.parents:
        return f"refusing to quarantine the quarantine root tree ({root})"
    if resolved.parent == Path(resolved.anchor):  # direct child of /
        return f"refusing to quarantine a top-level system path ({resolved})"
    if str(resolved) in _SYSTEM_TOP:
        return f"refusing to quarantine a system path ({resolved})"
    return None


def _batch_dir(root: Path, batch_id: str) -> Path:
    batch = root / batch_id
    suffix = 2
    while batch.exists():  # same-second collision: -2, -3, …
        batch = root / f"{batch_id}-{suffix}"
        suffix += 1
    return batch


def cmd_mv(paths: list[str]) -> int:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    os.chmod(root, 0o700)

    sources: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if not path.exists() and not path.is_symlink():
            print(f"quarantine: ERROR path does not exist: {raw}", file=sys.stderr)
            return 3
        reason = _refusal(path, root)
        if reason:
            print(f"quarantine: ERROR {reason}: {raw}", file=sys.stderr)
            return 2
        sources.append(path)

    batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    batch = _batch_dir(root, batch_id)
    batch.mkdir(parents=True)
    manifest = {
        "id": batch.name,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "entries": [],
    }

    taken: set[str] = set()
    for src in sources:
        dest_name = src.name or "unnamed"
        candidate = dest_name
        n = 2
        while candidate in taken:  # same-batch basename collision
            candidate = f"{dest_name}--{n}"
            n += 1
        taken.add(candidate)
        dest = batch / candidate
        entry_type = "symlink" if src.is_symlink() else ("dir" if src.is_dir() else "file")
        before = [
            {"rel": str(p.relative_to(src)), "sha256": _sha256(p), "size": p.stat().st_size}
            for p in _files_under(src)
        ]
        mtime = src.stat().st_mtime
        shutil.move(str(src), str(dest))
        after = [
            {"rel": str(p.relative_to(dest)), "sha256": _sha256(p), "size": p.stat().st_size}
            for p in _files_under(dest)
        ]
        verified = sorted(before, key=lambda e: e["rel"]) == sorted(after, key=lambda e: e["rel"])
        manifest["entries"].append(
            {
                "original": str(Path(os.path.abspath(src))),
                "quarantined": str(dest),
                "type": entry_type,
                "mtime": mtime,
                "files": after,
                "verified": verified,
            }
        )

    (batch / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    unverified = [e["original"] for e in manifest["entries"] if not e["verified"]]
    total = sum(f["size"] for e in manifest["entries"] for f in e["files"])
    print(f"quarantine: batch {batch.name} · {len(manifest['entries'])} entries · {total} bytes")
    print(f"quarantine: manifest {batch / 'manifest.json'}")
    for entry in manifest["entries"]:
        print(f"  {entry['original']} -> {entry['quarantined']} ({entry['type']})")
    if unverified:
        print(
            "quarantine: ERROR post-move sha256 mismatch for: "
            + ", ".join(unverified)
            + " — RESTORE BY HAND before continuing (do not trust this batch)",
            file=sys.stderr,
        )
        return 4
    print("quarantine: verified (post-move sha256 EQUAL) — reversible via the manifest")
    return 0


def cmd_show(batch_id: str | None) -> int:
    root = _root()
    if batch_id:
        manifest_path = root / batch_id / "manifest.json"
        if not manifest_path.is_file():
            print(f"quarantine: no such batch: {batch_id}", file=sys.stderr)
            return 3
        print(json.dumps(json.loads(manifest_path.read_text()), indent=2))
        return 0
    if not root.is_dir():
        print(f"quarantine: nothing quarantined yet (root {root})")
        return 0
    for batch in sorted(root.iterdir()):
        manifest_path = batch / "manifest.json"
        if manifest_path.is_file():
            data = json.loads(manifest_path.read_text())
            total = sum(f["size"] for e in data["entries"] for f in e["files"])
            print(
                f"{data['id']}  {len(data['entries'])} entries  {total} bytes  "
                f"{data['created_utc']}"
            )
        else:
            print(f"{batch.name}  (no manifest)")
    return 0


def cmd_prune(days: int, yes: bool) -> int:
    root = _root()
    if not root.is_dir():
        print(f"quarantine: nothing to prune (root {root})")
        return 0
    if not yes:
        print(
            "quarantine: prune DROPS quarantined data for real — rerun with --yes "
            "(the human's or a timer's job; the agent never prunes)",
            file=sys.stderr,
        )
        return 2
    cutoff = time.time() - days * SECONDS_PER_DAY
    removed = 0
    for batch in sorted(root.iterdir()):
        if batch.stat().st_mtime < cutoff:
            shutil.rmtree(batch)
            removed += 1
            print(f"quarantine: pruned {batch.name}")
    print(f"quarantine: prune done · {removed} batches older than {days} days")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="the agent's only way to remove something")
    sub = parser.add_subparsers(dest="cmd", required=True)
    mv = sub.add_parser("mv", help="move paths into a new quarantine batch")
    mv.add_argument("paths", nargs="+")
    show = sub.add_parser("show", help="list batches / show one manifest")
    show.add_argument("batch_id", nargs="?")
    prune = sub.add_parser("prune", help="human or timer only: drop batches older than --days")
    prune.add_argument("--days", type=int, default=30)
    prune.add_argument("--yes", action="store_true", help="required: prune deletes for real")
    args = parser.parse_args(argv)
    if args.cmd == "mv":
        return cmd_mv(args.paths)
    if args.cmd == "show":
        return cmd_show(args.batch_id)
    return cmd_prune(args.days, args.yes)


if __name__ == "__main__":
    sys.exit(main())
