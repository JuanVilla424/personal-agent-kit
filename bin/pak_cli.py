#!/usr/bin/env python3
"""pak_cli.py — the kit's one command line (bin/pak).

pak doctor                    every layer and its real state; exit 1 if a required one fails
pak guard "<command>"         judge a command (bin/auto_guard.py; also approve, --status…)
pak memory search|add|brief|consolidate …   (local/scripts/memory_index/memory.py)
pak lessons add|list|expired …              (bin/lessons.py)
pak brain backup|list|restore|prune …       (bin/brain_backup.py)
pak brain-health               the brain's per-task health check (bin/brain-health.sh)
pak task add|run|status|image …             (bin/pak_worker.py)
pak quarantine mv|show …                    (bin/quarantine.py)
pak snapshot take|list|show|diff|restore …  (bin/snapshot.py)
pak eval guard|memory         the guard's corpus and held-out benchmark, or the memory benchmark
pak import hermes [--dir D]   bring Hermes Agent's MEMORY.md and USER.md into the memory
"""

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))
MEMORY_CLI = REPO_ROOT / "local" / "scripts" / "memory_index" / "memory.py"
PASSTHROUGH = {
    "guard": REPO_ROOT / "bin" / "auto_guard.py",
    "memory": MEMORY_CLI,
    "lessons": REPO_ROOT / "bin" / "lessons.py",
    "task": REPO_ROOT / "bin" / "pak_worker.py",
    "quarantine": REPO_ROOT / "bin" / "quarantine.py",
    "snapshot": REPO_ROOT / "bin" / "snapshot.py",
}
# Snapshots are never pruned for the human: past this size doctor says so.
SNAPSHOT_WARN_BYTES = 5 * 1024**3
REQUIRED_HOOKS = ("auto-guard.py", "url-guard.py", "pre-write-guard.sh")
HEALTH_TIMEOUT_S = 3
SYMBOLS = {"ok": "✔", "warn": "!", "fail": "✘", "off": "–"}
# Hermes Agent separates the entries of its memory files with a line holding only this sign.
HERMES_ENTRY_SEP = re.compile(r"^\s*§\s*$", re.MULTILINE)
HERMES_FILES = {"USER.md": "style", "MEMORY.md": "other"}


def python() -> str:
    venv = REPO_ROOT / ".venv" / "bin" / "python3"
    return str(venv) if venv.exists() else sys.executable


# ── doctor ───────────────────────────────────────────────────────────────────────────────────────


def check_guard() -> tuple[str, str]:
    import auto_guard

    s = auto_guard.status()
    detail = f"{s['stage1']['rules']} rules; Stage 2 {s['stage2']['state']}"
    if s["auto_approve"]:
        return "warn", detail + "; auto-approval ON: challenges pass without asking"
    return "ok", detail + "; challenges ask the human"


def check_claude_hooks(home: Path) -> tuple[str, str]:
    settings = home / ".claude" / "settings.json"
    text = settings.read_text(encoding="utf-8") if settings.exists() else ""
    missing = [hook for hook in REQUIRED_HOOKS if hook not in text]
    if missing:
        return "fail", f"missing in {settings}: {', '.join(missing)} (bash bin/install.sh)"
    return "ok", "guard hooks registered for every project"


def check_opencode(home: Path) -> tuple[str, str]:
    config = (
        Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config") / "opencode" / "opencode.json"
    )
    if not config.exists():
        return "off", "not configured (bash bin/install-opencode.sh)"
    plugins = json.loads(config.read_text(encoding="utf-8")).get("plugin") or []
    expected = len(list((REPO_ROOT / ".opencode" / "plugins").glob("*.js")))
    if len(plugins) < expected:
        return (
            "fail",
            f"{len(plugins)} of {expected} plugins in {config} (bash bin/opencode/build-config.sh)",
        )
    pin = (REPO_ROOT / "configs" / "opencode.version").read_text(encoding="utf-8").strip()
    binary = shutil.which("opencode")
    version = ""
    if binary:
        version = subprocess.run(
            [binary, "--version"], capture_output=True, text=True, timeout=30, check=False
        ).stdout.strip()
    if pin not in version:
        return (
            "warn",
            f"plugins in every project, but OpenCode is '{version or 'missing'}', not {pin}",
        )
    return "ok", f"{expected} plugins in every project, OpenCode {pin}"


def check_memory() -> tuple[str, str]:
    url = (
        os.environ.get("MEMORY_SERVICE_URL", "http://localhost:7700").rstrip("/") + "/memory/health"
    )
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_S) as resp:
            health = json.loads(resp.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        return "fail", f"memory_service does not answer at {url} ({type(e).__name__})"
    if health.get("status") != "ok":
        return "fail", f"memory_service degraded: {health.get('error', '?')}"
    return (
        "ok",
        f"{health.get('user_entries', 0)} personal and {health.get('entries', 0)} shared memories",
    )


def check_consolidation() -> tuple[str, str]:
    if not shutil.which("systemctl"):
        return "off", "no systemd: run `pak memory consolidate` yourself"
    active = subprocess.run(
        ["systemctl", "is-active", "--quiet", "agent-memory-consolidate.timer"],
        timeout=30,
        check=False,
    ).returncode
    return (
        ("ok", "nightly at 03:30") if active == 0 else ("warn", "the nightly timer is not active")
    )


def check_brain_backup() -> tuple[str, str]:
    import brain_backup

    age = brain_backup.latest_age_hours()
    if age is None:
        return "off", f"none yet in {brain_backup.root()}: pak brain backup"
    if age > 24 * 7:
        return "warn", f"the newest generation is {age / 24:.0f} days old: pak brain backup"
    return "ok", f"the newest generation is {age:.0f}h old"


def check_lessons() -> tuple[str, str]:
    import lessons

    from datetime import date

    due = [lesson for lesson in lessons.load() if lessons.is_expired(lesson, date.today())]
    if due:
        return "warn", f"{len(due)} control(s) due for review: pak lessons expired"
    return "ok", f"{len(lessons.load())} lessons, none expired"


def check_slack() -> tuple[str, str]:
    env_file = REPO_ROOT / "local" / "scripts" / "notify" / ".env"
    if not env_file.exists():
        return "off", "not installed (bash bin/install.sh --with-slack)"
    values = dict(
        line.split("=", 1)
        for line in env_file.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    )
    users = [u for u in values.get("SLACK_ALLOWED_USERS", "").split(",") if u.strip()]
    channels = [c for c in values.get("SLACK_CHANNEL_IDS", "").split(",") if c.strip()]
    if not users or not channels:
        return (
            "ok",
            "closed: it answers nobody until SLACK_CHANNEL_IDS and SLACK_ALLOWED_USERS list who",
        )
    return "ok", f"answers {len(users)} user(s) in {len(channels)} channel(s)"


def check_snapshots() -> tuple[str, str]:
    import snapshot

    root = snapshot.root()
    stores = sorted(root.glob("*.git")) if root.is_dir() else []
    if not stores:
        return "off", f"none yet in {root}: the next session takes the first"
    size = sum(f.stat().st_size for store in stores for f in store.rglob("*") if f.is_file())
    detail = f"{len(stores)} project(s), {size / 1024**2:.0f} MiB in {root}"
    if size > SNAPSHOT_WARN_BYTES:
        return "warn", detail + ": nothing prunes them, so old ones are yours to clear"
    return "ok", detail


def check_worker() -> tuple[str, str]:
    import pak_worker

    if not shutil.which("docker"):
        return "off", "no Docker: tasks run only when queued with --isolation host"
    problem = pak_worker.container_problem()
    if problem:
        return "warn", problem
    tag = pak_worker.image_tag()
    if not pak_worker.image_present():
        return "warn", f"{tag} is not built yet: pak task image"
    return "ok", f"tasks run in {tag}, with no network but the model API"


CHECKS = [
    ("Guard", check_guard),
    ("Snapshots", check_snapshots),
    ("Worker", check_worker),
    ("Claude Code", lambda: check_claude_hooks(Path.home())),
    ("OpenCode", lambda: check_opencode(Path.home())),
    ("Memory", check_memory),
    ("Consolidation", check_consolidation),
    ("Brain backup", check_brain_backup),
    ("Lessons", check_lessons),
    ("Slack", check_slack),
]


def doctor() -> int:
    failed = False
    for name, check in CHECKS:
        try:
            state, detail = check()
        except Exception as e:  # pylint: disable=broad-except
            state, detail = "fail", f"the check itself failed: {type(e).__name__}: {e}"
        failed = failed or state == "fail"
        print(f"{SYMBOLS[state]} {name:14} {detail}")
    return 1 if failed else 0


# ── import hermes ────────────────────────────────────────────────────────────────────────────────


def hermes_entries(text: str) -> list[str]:
    """The entries of a Hermes memory file: `§` lines separate them; a file without any is split
    on blank lines."""
    parts = (
        HERMES_ENTRY_SEP.split(text)
        if HERMES_ENTRY_SEP.search(text)
        else re.split(r"\n\s*\n", text)
    )
    entries = []
    for part in parts:
        entry = " ".join(line.strip().lstrip("-*").strip() for line in part.splitlines()).strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return entries


def import_hermes(directory: Path) -> int:
    found = [
        (directory / name, category)
        for name, category in HERMES_FILES.items()
        if (directory / name).exists()
    ]
    if not found:
        print(f"pak import: no MEMORY.md or USER.md in {directory}", file=sys.stderr)
        return 2
    imported = refused = 0
    for path, category in found:
        for entry in hermes_entries(path.read_text(encoding="utf-8")):
            proc = subprocess.run(
                [python(), str(MEMORY_CLI), "add", entry, "--category", category],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if "remembered" in proc.stdout:
                imported += 1
            else:
                refused += 1
                print(f"not imported: {entry[:70]}", file=sys.stderr)
    print(f"pak import: {imported} memories imported from Hermes, {refused} not imported")
    return 0 if imported else 1


# ── main ─────────────────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0
    command, rest = argv[0], argv[1:]
    if command == "doctor":
        return doctor()
    if command in PASSTHROUGH:
        return subprocess.run([python(), str(PASSTHROUGH[command]), *rest], check=False).returncode
    if command == "brain" and rest[:1] == ["health"]:
        script = REPO_ROOT / "bin" / "brain-health.sh"
        return subprocess.run(["bash", str(script), *rest[1:]], check=False).returncode
    if command == "brain":
        import brain_backup

        return brain_backup.main(rest)
    if command == "eval" and rest[:1] == ["guard"]:
        test = REPO_ROOT / "bin" / "tests" / "test_guard_corpus.py"
        corpus = subprocess.run(
            [python(), "-m", "pytest", "-q", "-o", "addopts=", str(test)], check=False
        ).returncode
        bench = REPO_ROOT / "evals" / "guard_benchmark.py"
        return corpus or subprocess.run([python(), str(bench), *rest[1:]], check=False).returncode
    if command == "eval" and rest[:1] == ["memory"]:
        bench = REPO_ROOT / "evals" / "memory_benchmark.py"
        return subprocess.run([python(), str(bench), *rest[1:]], check=False).returncode
    if command == "import" and rest[:1] == ["hermes"]:
        directory = (
            Path(rest[2]).expanduser()
            if rest[1:2] == ["--dir"] and len(rest) > 2
            else Path.home() / ".hermes" / "memories"
        )
        return import_hermes(directory)
    print(f"pak: unknown command: {' '.join(argv)} (pak help)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
