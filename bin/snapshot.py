#!/usr/bin/env python3
"""snapshot.py — a copy of the working tree before the agent works, kept outside the repository.

The guard reads commands. A script written to disk and then run is not a command it can read, so
the repository is copied first: whatever such a script does to it can be undone. Every session
starts with a snapshot (Claude Code's SessionStart hook, OpenCode's session.created), and so does
every challenge, before the human answers it.

Each project gets its own bare git repository under ~/.pak/snapshots (PAK_SNAPSHOTS_DIR overrides
it), used with --git-dir there and --work-tree on the project: the project's own .git is never
written, no branch is created and nothing is stashed. A snapshot holds what git sees in the work
tree, .gitignore respected; files over PAK_SNAPSHOT_MAX_FILE_MB (20) are left out. An unchanged
tree is not taken again. Nothing here deletes a snapshot: pruning is the human's.

Usage:
  bin/snapshot.py take [DIR] [--reason WHY]          # DIR defaults to the current directory
  bin/snapshot.py list [DIR]
  bin/snapshot.py show ID [PATH] [--dir DIR]         # a snapshot's files, or one file's content
  bin/snapshot.py diff ID [--dir DIR]                # what changed in the work tree since then
  bin/snapshot.py restore ID [PATH ...] [--dir DIR]  # takes a snapshot first; deletes nothing

Exit codes: 0 ok · 1 nothing done (not a git work tree, or another snapshot is running) · 2 error.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_ROOT = Path("~/.pak/snapshots").expanduser()
DEFAULT_MAX_FILE_MB = 20.0
REF = "refs/pak/snapshots"
GIT_TIMEOUT_S = 300
IDENTITY = {
    "GIT_AUTHOR_NAME": "pak snapshot",
    "GIT_AUTHOR_EMAIL": "snapshot@pak.invalid",
    "GIT_COMMITTER_NAME": "pak snapshot",
    "GIT_COMMITTER_EMAIL": "snapshot@pak.invalid",
}
# Set by a caller's git, they would point these commands at the project's own repository.
_GIT_ENV_OVERRIDES = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)
_GLOB_SPECIALS = re.compile(r"([\\*?\[\]!# ])")


class SnapshotError(Exception):
    """A git step failed; the message says which and why."""


def root() -> Path:
    return Path(os.environ.get("PAK_SNAPSHOTS_DIR") or DEFAULT_ROOT).expanduser()


def max_file_bytes() -> int:
    raw = os.environ.get("PAK_SNAPSHOT_MAX_FILE_MB") or ""
    try:
        megabytes = float(raw) if raw else DEFAULT_MAX_FILE_MB
    except ValueError:
        megabytes = DEFAULT_MAX_FILE_MB
    return int(max(megabytes, 0) * 1024 * 1024)


def _git(*args: str, cwd: Path | None = None, extra_env: dict | None = None) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _GIT_ENV_OVERRIDES}
    env.update({"GIT_TERMINAL_PROMPT": "0", **(extra_env or {})})
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    if proc.returncode != 0:
        raise SnapshotError(
            f"git {args[2] if args[:1] == ('--git-dir',) else args[0]}: "
            f"{proc.stderr.strip()[:300]}"
        )
    return proc.stdout


def toplevel(directory: Path) -> Path | None:
    try:
        return Path(_git("-C", str(directory), "rev-parse", "--show-toplevel").strip())
    except (SnapshotError, OSError):
        return None


def store_for(top: Path) -> Path:
    digest = hashlib.sha1(str(top).encode("utf-8")).hexdigest()[:12]
    return root() / f"{top.name}-{digest}.git"


def _base(store: Path, top: Path) -> list[str]:
    return ["--git-dir", str(store), "--work-tree", str(top)]


def _ensure_store(store: Path) -> None:
    if (store / "HEAD").exists():
        return
    root().mkdir(parents=True, exist_ok=True)
    root().chmod(0o700)
    _git("init", "--bare", "--quiet", str(store))


def _exclude_big_files(store: Path, top: Path) -> int:
    """Copy the project's info/exclude, and add every file over the size limit: a large file is
    left out before git ever reads it."""
    limit = max_file_bytes()
    listed = _git(
        *_base(store, top), "ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=top
    )
    big = []
    for rel in filter(None, listed.split("\0")):
        try:
            if (top / rel).is_file() and (top / rel).stat().st_size > limit:
                big.append("/" + _GLOB_SPECIALS.sub(r"\\\1", rel))
        except OSError:
            continue
    own = top / ".git" / "info" / "exclude"
    lines = own.read_text(encoding="utf-8", errors="replace").splitlines() if own.is_file() else []
    exclude = store / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text("\n".join([*lines, *big]) + "\n", encoding="utf-8")
    if big:  # one taken before it grew stays out of the next snapshot too
        _git(
            *_base(store, top),
            "rm",
            "--cached",
            "--quiet",
            "--ignore-unmatch",
            "--",
            *[b[1:].replace("\\", "") for b in big],
            cwd=top,
        )
    return len(big)


def take(directory: Path, reason: str = "manual") -> tuple[int, str]:
    top = toplevel(directory)
    if top is None:
        return 1, f"{directory} is not inside a git work tree: nothing to snapshot"
    store = store_for(top)
    _ensure_store(store)
    with open(store / "pak-snapshot.lock", "w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return 1, f"another snapshot of {top} is running"
        skipped = _exclude_big_files(store, top)
        base = _base(store, top)
        _git(*base, "add", "-A", "--ignore-errors", "--", ".", cwd=top)
        tree = _git(*base, "write-tree", cwd=top).strip()
        try:
            parent = _git(*base, "rev-parse", "--verify", "--quiet", f"{REF}^{{commit}}").strip()
        except SnapshotError:
            parent = ""
        if parent and _git(*base, "rev-parse", f"{parent}^{{tree}}").strip() == tree:
            return 0, f"unchanged since {parent[:12]}"
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        commit = _git(
            *base,
            "commit-tree",
            tree,
            *(["-p", parent] if parent else []),
            "-m",
            reason,
            "-m",
            f"{top}\n{stamp}",
            extra_env=IDENTITY,
        ).strip()
        _git(*base, "update-ref", REF, commit, *([parent] if parent else []))
    note = f", {skipped} large file(s) left out" if skipped else ""
    return 0, f"snapshot {commit[:12]} of {top} ({reason}{note})"


def history(top: Path) -> list[tuple[str, str, str]]:
    """(id, date, reason) of every snapshot of the project, newest first."""
    store = store_for(top)
    if not (store / "HEAD").exists():
        return []
    try:
        out = _git("--git-dir", str(store), "log", "--format=%H%x1f%cI%x1f%s", REF)
    except SnapshotError:
        return []
    return [tuple(line.split("\x1f", 2)) for line in out.splitlines() if line]  # type: ignore[misc]


def restore(directory: Path, snapshot_id: str, paths: list[str]) -> tuple[int, str]:
    """Write a snapshot's files back into the work tree: a snapshot of the current state comes
    first, and a file the snapshot does not have is left alone."""
    top = toplevel(directory)
    if top is None:
        return 1, f"{directory} is not inside a git work tree"
    code, message = take(top, reason=f"before restoring {snapshot_id[:12]}")
    if code:
        return code, f"not restored: {message}"
    targets = [os.path.relpath(Path(p).resolve(), top) for p in paths] or ["."]
    _git(*_base(store_for(top), top), "checkout", snapshot_id, "--", *targets, cwd=top)
    return 0, f"restored {', '.join(targets)} from {snapshot_id[:12]} ({message})"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="snapshots of a work tree, kept outside it")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_take = sub.add_parser("take", help="snapshot the work tree of DIR")
    p_take.add_argument("dir", nargs="?", default=".")
    p_take.add_argument("--reason", default="manual")
    p_list = sub.add_parser("list", help="the snapshots of DIR's project, newest first")
    p_list.add_argument("dir", nargs="?", default=".")
    for name, text in (("show", "a snapshot's files, or one file"), ("diff", "changes since")):
        p = sub.add_parser(name, help=text)
        p.add_argument("id")
        if name == "show":
            p.add_argument("path", nargs="?")
        p.add_argument("--dir", default=".")
    p_restore = sub.add_parser("restore", help="write a snapshot back; deletes nothing")
    p_restore.add_argument("id")
    p_restore.add_argument("paths", nargs="*")
    p_restore.add_argument("--dir", default=".")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "take":
            code, message = take(Path(args.dir), args.reason)
        elif args.cmd == "restore":
            code, message = restore(Path(args.dir), args.id, args.paths)
        else:
            top = toplevel(Path(args.dir))
            if top is None:
                print(f"pak snapshot: {args.dir} is not inside a git work tree", file=sys.stderr)
                return 1
            if args.cmd == "list":
                rows = history(top)
                for snapshot_id, date, reason in rows:
                    print(f"{snapshot_id[:12]}  {date}  {reason}")
                print(f"{len(rows)} snapshot(s) of {top} in {store_for(top)}")
                return 0
            base = _base(store_for(top), top)
            if args.cmd == "show":
                what = f"{args.id}:{args.path}" if args.path else args.id
                cmd = ["show", what] if args.path else ["ls-tree", "-r", "--name-only", args.id]
                print(_git(*base, *cmd, cwd=top), end="")
            else:
                print(_git(*base, "diff", "--stat", args.id, cwd=top), end="")
            return 0
    except (SnapshotError, OSError, subprocess.TimeoutExpired) as e:
        print(f"pak snapshot: {e}", file=sys.stderr)
        return 2
    print(message, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
