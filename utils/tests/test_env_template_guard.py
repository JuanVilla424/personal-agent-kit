"""Guard: every env var read by first-party code must be documented.

Scans the repo's Python sources for os.getenv / os.environ and requires
every variable to appear in one of the committed .env.template files (or in the
allowlist of system/runtime variables that don't belong in a template).
Prevents recurring drift: new config lands in code or a crontab but
never in the template (bit us twice: the 2026-06-30 audit fixed 9 vars,
the 2026-07-03 one found 4 more). Scope: Python; crontab's inline vars
are documented by hand in .env.template (see the snapshot/restore section)."""

import re
from pathlib import Path

import pytest
from dotenv import dotenv_values

REPO_ROOT = Path(__file__).resolve().parents[2]

SCAN_DIRS = [
    "local/scripts",
    "local/hooks",
    "local/monitoring",
    "utils",
    "evals",
    "memory-service",
    "bin",
]

TEMPLATES = [
    ".env.template",
    "local/scripts/notify/.env.template",
    "local/monitoring/.env.template",
]

# Generated/vendored directories — never first-party.
EXCLUDE_PARTS = {"venv", ".venv", "node_modules", "__pycache__", "temp", "logs"}

# System/runtime vars that do NOT belong in a template: injected by the OS, CI,
# the agent's harness, or the one-off invocation — documenting them would just be noise.
ALLOWLIST = {
    # OS / shell
    "HOME",
    "PATH",
    "USER",
    "HOSTNAME",
    "LANG",
    "SHELL",
    "PWD",
    "TERM",
    "TZ",
    # AWS SDK/CLI (profiles and credentials live in ~/.aws, not in .env)
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    # CI (injected by GitLab/GitHub)
    "CI",
    "CI_PROJECT_DIR",
    "CI_COMMIT_BRANCH",
    "GITHUB_ACTIONS",
    # Python runtime
    "PYTHONPATH",
    "VIRTUAL_ENV",
    # Hook re-entrancy guards (a hook sets this on its own subprocesses,
    # never real user config) — see post-write-judge.sh.
    "PAK_HOOK_RUNNING",
    # The tests point the guard's audit trail and approvals at temp files.
    "AUTO_GUARD_LOG",
    "AUTO_GUARD_APPROVALS",
    # The XDG base directory, set by the desktop session, not by this kit.
    "XDG_CONFIG_HOME",
}

GETENV_RE = re.compile(
    r"""os\.(?:getenv|environ\.get)\(\s*['"]([A-Z][A-Z0-9_]*)['"]"""
    r"""|os\.environ\[\s*['"]([A-Z][A-Z0-9_]*)['"]\s*\]"""
)

# Documented-but-commented-out keys count too in templates ("# VAR=...").
TEMPLATE_KEY_RE = re.compile(r"^#?\s*([A-Z][A-Z0-9_]*)=")


def template_keys() -> set:
    keys = set()
    for rel in TEMPLATES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = TEMPLATE_KEY_RE.match(line.strip())
            if match:
                keys.add(match.group(1))
    return keys


def scanned_usages() -> dict:
    hits = {}
    for rel in SCAN_DIRS:
        base = REPO_ROOT / rel
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if any(part in EXCLUDE_PARTS for part in path.parts):
                continue
            # Tests configure their own fixture vars — not operational config.
            if path.name.startswith("test_") or path.name == "conftest.py":
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for match in GETENV_RE.finditer(text):
                var = match.group(1) or match.group(2)
                hits.setdefault(var, set()).add(str(path.relative_to(REPO_ROOT)))
    return hits


def test_templates_exist():
    root_template = REPO_ROOT / ".env.template"
    assert (
        root_template.exists()
    ), ".env.template at the root is missing — it's the committed config doc"


def test_all_env_vars_documented_in_templates():
    documented = template_keys() | ALLOWLIST
    hits = scanned_usages()
    missing = {var: sorted(files) for var, files in sorted(hits.items()) if var not in documented}
    detail = "\n".join(f"  {var}  ←  {', '.join(files)}" for var, files in missing.items())
    assert not missing, (
        "Env vars read by the code but missing from every .env.template "
        "(document it in the right template, or if the "
        f"system/CI/harness injects it, add it to ALLOWLIST):\n{detail}"
    )


@pytest.mark.parametrize(
    "template",
    [
        ".env.template",
        "local/monitoring/.env.template",
        "local/scripts/memory_index/.env.template",
        "local/scripts/excel_report_generator/.env.template",
        "local/scripts/notify/.env.template",
        "local/scripts/pdf_report_generator/.env.template",
    ],
)
def test_a_comment_never_becomes_a_value(template):
    """After an empty `KEY=`, dotenv reads a trailing comment as the value. A copied template would
    then ship the token of its own example as a live credential."""
    values = dotenv_values(REPO_ROOT / template)
    assert not {key for key, value in values.items() if (value or "").startswith("#")}
