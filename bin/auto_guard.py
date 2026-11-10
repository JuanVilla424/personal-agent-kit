#!/usr/bin/env python3
"""auto_guard.py — the shared guard: every agent's mutations go through these rules.

Reasoning-blind: the guard sees only the proposed action and the user's intent, never the agent's
reasoning or a tool result. An agent cannot talk it into a bad decision, and an injection that
arrives inside a tool result does not reach it.

Two stages:
  Stage 1: deterministic rules (regex, no LLM, under 1 ms). Always on.
  Stage 2: the decision layer (bin/decision.py). Optional: it runs only with OPENROUTER_API_KEY.
           Without the key it is off, not broken: Stage 1 still decides, and a challenge asks the
           human.

Deny and continue: a block does not end the session. It returns a structured error telling the
agent to find another way. 3 consecutive or 20 total denials in one process become a halt.

Challenges ask the human. With auto-approval off, the default, Claude Code shows its native
dialog and OpenCode, which has no dialog, blocks and prints the command the human types to approve
that exact action. configs/auto-guard.json can turn auto-approval on: a challenge then passes and
is logged with severity "auto_approved". A block is never approved by anything.

Stdlib only: the hook and the plugin import this module with any python3.
"""

import ast
import fcntl
import hashlib
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shell_parse  # noqa: E402  stdlib only, next to this file: reads the command as bash will

THIS = Path(__file__).resolve()
REPO_ROOT = THIS.parents[1]
AUTO_GUARD_CONFIG = REPO_ROOT / "configs" / "auto-guard.json"
AUTO_APPROVED = "auto_approved"
# Absolute: the hooks are global, and a session in another repo has no protocols/ of its own.
PROTOCOL = f"{REPO_ROOT / 'protocols' / 'decision-protocol.md'} §How to use the guard"
APPROVE_CMD = f"python3 {THIS} approve"


def auto_approve_settings() -> dict:
    """{"enabled": bool, "applies_to": [...]} from configs/auto-guard.json → `auto_approve`.

    An unreadable config means disabled: a challenge asks the human. There is no environment
    override on purpose: the config file is the one place an agent is blocked from changing.
    `applies_to` defaults to ["challenge"]: an `engine_unavailable` is only auto-approved when the
    config lists it, so a broken engine stays fail-closed.
    """
    try:
        data = json.loads(AUTO_GUARD_CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    cfg = (data.get("auto_approve") if isinstance(data, dict) else None) or {}
    applies = cfg.get("applies_to")
    if not isinstance(applies, list):
        applies = ["challenge"]
    return {"enabled": cfg.get("enabled") is True, "applies_to": [str(x) for x in applies]}


def auto_approve_enabled() -> bool:
    """Whether challenges are approved automatically."""
    return auto_approve_settings()["enabled"]


def stage2_enabled() -> bool:
    """Whether the decision layer can run: it needs OPENROUTER_API_KEY."""
    sys.path.insert(0, str(REPO_ROOT / "bin"))
    from decision import engine_key

    return bool(engine_key())


# ── Credential exfiltration: what never downgrades, and what does ────────────────────────────────

# Files whose content is a secret. Each name stops before a suffix: `.env.template` and
# `id_rsa.pub` are not secrets.
_CRED_FILE = (
    r"(?:\.env|\.netrc|\.npmrc|\.pypirc|\.pgpass|id_rsa|id_ed25519|credentials(?:\.json)?)"
    r"(?![\w.-])"
)
_SEND_FLAG = r"(?:--data|-d|--post-(?:data|file)|--form|--upload-file|(?<!\S)(?-i:-[dFT]))"
_CRED_WORD = r"(?:api.?key|token|passw(?:or)?d|secret)"
_AUTH_FLOW_RE = re.compile(r"auth\.docker\.io/token", re.IGNORECASE)
_LOOPBACK_URL_RE = re.compile(
    r"https?://(?:localhost|127(?:\.\d{1,3}){3}|172\.17\.0\.1|\[?::1\]?)(?::\d+)?(?:[/?#:]|$)",
    re.IGNORECASE,
)
# Obviously fake credentials (probes, tests, docs) are never a real secret worth a block.
_TEST_CRED_RE = re.compile(
    r"(?:username|user|passwd|password|pwd|token|api[_-]?key|secret)[\"']?\s*[:=]\s*[\"']?"
    r"(?:nobody|wrong|test|testing|dummy|example|sample|placeholder|changeme|fake|"
    r"<[^>]{1,30}>|your[_-][a-z]+|x{3,}|0{4,})(?:[&\"'\s]|$)",
    re.IGNORECASE,
)
# The same, for a bare value torn out of a URL query (`?token=abc`).
_FAKE_VALUE_RE = re.compile(
    r"^(?:nobody|wrong|test|testing|dummy|example|sample|placeholder|changeme|fake|"
    r"x{3,}|0{4,}|abc|xyz|123|321|qwerty|redacted)$",
    re.IGNORECASE,
)


def _exfil_downgrade(action_text: str) -> bool:
    """True when nothing real leaves: loopback targets, the Docker Hub token flow, fake values."""
    if _AUTH_FLOW_RE.search(action_text):
        return True
    urls = re.findall(r"https?://[^\s'\";|]+", action_text)
    if urls and all(_LOOPBACK_URL_RE.match(u) for u in urls):
        return True
    if re.search(_CRED_FILE, action_text):
        return False  # a credential file going out is never a probe
    # Only explicit `key=value` pairs count: `@-` or `@.env` is a credential file feeding the
    # request and never downgrades, and every pair, query tokens included, must be fake or free.
    query_vals = re.findall(
        r"[?&][a-z0-9_]*(?:api.?key|token|passw(?:or)?d|secret)[a-z0-9_]*=([^\s'\"&;]+)",
        action_text,
    )
    payloads = [
        a or b or c
        for a, b, c in re.findall(
            r"(?:--data|--form|-d|-F)\s+(?:\"([^\"]*)\"|'([^']*)'|(\S+))", action_text
        )
    ]
    data_pairs = [p for p in payloads if "=" in p]
    return bool(
        (query_vals or data_pairs)
        and all(_FAKE_VALUE_RE.match(v) for v in query_vals)
        and all(
            _TEST_CRED_RE.search(p) or not re.search(r"passw|token|secret|api.?key|user", p, re.I)
            for p in data_pairs
        )
    )


# ── What the parsed command shows (bin/shell_parse.py) ───────────────────────────────────────────

# Generators whose output is environment setup, the code `eval` and `source` are meant to run.
_ENV_SETUP_PROGRAMS = frozenset({"ssh-agent", "gpg-agent", "keychain", "dircolors"})
_ENV_SETUP_WORDS = frozenset(
    {"completion", "completions", "init", "hook", "shellenv", "env", "activate"}
)
_INTERPRETER = re.compile(r"^(?:python[0-9.]*|perl|ruby|node|php)$")
_PIPE_INTO_STDIN = ("/dev/stdin", "/dev/fd/", "/proc/self/fd/")


def _generates_setup(word: shell_parse.Word) -> bool:
    """Whether every command in the word's substitutions prints environment setup."""
    visits = [v for sub in word.subs for v in shell_parse.walk(sub) if v.effective]
    return bool(visits) and all(
        v.effective[0] in _ENV_SETUP_PROGRAMS or bool(_ENV_SETUP_WORDS & set(v.effective[1:]))
        for v in visits
    )


def _runs_generated_code(visit: shell_parse.Visit) -> bool:
    """`source <(…)`, `. /dev/stdin`, `bash <(…)`: a program handed a script that only exists at
    run time."""
    program = visit.effective[0]
    if program not in ("source", ".", *shell_parse.SHELLS) and not _INTERPRETER.match(program):
        return False
    script = next((w for w in visit.words[1:] if not w.text.startswith("-")), None)
    if script is None:
        return False
    if script.subs:
        return not _generates_setup(script)
    return program in ("source", ".") and script.text.startswith(_PIPE_INTO_STDIN)


def _dynamic_code(script: shell_parse.Script) -> bool:
    """Code the text never spells out: a program built at run time, generated code handed to
    `eval` or `source`, or nesting too deep to read."""
    if script.too_deep:
        return True
    for visit in shell_parse.walk(script):
        if not visit.effective:
            continue
        if visit.dynamic and not _generates_setup(visit.words[0]):
            return True
        if _runs_generated_code(visit):
            return True
    return False


# Folders that hold credentials. In ~/.ssh the public half is not a secret.
_SECRET_DIR = re.compile(
    r"(?:^|[/~])\.(?:ssh|aws|gnupg|kube|docker)(?:/|$)|(?:^|[/~])\.config/gcloud(?:/|$)"
)
_PUBLIC_SSH = re.compile(r"\.ssh/(?:[^/]+\.pub|known_hosts[^/]*|authorized_keys[^/]*|config)$")
_SECRET_FILE = re.compile(rf"(?:^|/){_CRED_FILE}", re.IGNORECASE)
# Options of the transfer tools that take a value: `-i ~/.ssh/key` is how ssh logs in, not data.
_TRANSFER_VALUE_OPTS = frozenset(
    {
        "-i",
        "-F",
        "-o",
        "-J",
        "-S",
        "-c",
        "-l",
        "-P",
        "-p",
        "-e",
        "-b",
        "-B",
        "-D",
        "-L",
        "-R",
        "-W",
        "-w",
        "-E",
        "-m",
        "-O",
        "-Q",
    }
)
_TRANSFER_TOOLS = frozenset({"ssh", "scp", "sftp", "rsync"})
_RAW_SENDERS = frozenset({"nc", "ncat", "netcat", "socat", "telnet"})
_HTTP_CLIENTS = frozenset({"curl", "wget", "http", "https", "xh"})
# A request whose body is read from stdin: what a pipe feeds it leaves the machine.
_STDIN_BODY = re.compile(
    r"(?:^|\s)(?:-d|--data(?:-binary|-urlencode|-ascii)?|-F|--form)\s+\S*@-(?:\s|$)"
    r"|(?:^|\s)(?:-T|--upload-file)\s+-(?:\s|$)"
    r"|--(?:post|body)-file=(?:-|/dev/stdin)(?:\s|$)"
    r"|(?:^|\s)--data(?:-binary|-urlencode)?=@-"
)
_REMOTE_PATH = re.compile(r"^(?:[\w.-]+@)?[\w.-]+:|^rsync://")
_SECRET_VARIABLE = re.compile(_CRED_WORD, re.IGNORECASE)


def _is_secret_path(text: str) -> bool:
    if _SECRET_FILE.search(text):
        return True
    if text.startswith("/proc/") and text.endswith("/environ"):
        return True
    return bool(_SECRET_DIR.search(text)) and not _PUBLIC_SSH.search(text)


def _operands(program: str, args: list[str]) -> list[str]:
    """The data words of a command; for the transfer tools, without their options' values."""
    if program == "ssh":
        return []  # what ssh names runs on the other side; only its stdin is sent
    if program not in _TRANSFER_TOOLS:
        return args
    out: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
        elif arg in _TRANSFER_VALUE_OPTS:
            skip = True
        elif not arg.startswith("-"):
            out.append(arg)
    return out


def _reads_secrets(visit: shell_parse.Visit) -> bool:
    """A dump of the environment, or a credential file or folder among its operands or input."""
    program, args = visit.effective[0], visit.effective[1:]
    if program == "env" and not visit.command.nested:
        return True  # `env` with nothing to run prints every variable
    if program in ("set", "export") and args in ([], ["-p"]):
        return True
    if program in ("declare", "typeset") and args and all(re.fullmatch(r"-[px]+", a) for a in args):
        return True
    if program == "printenv" and (not args or any(_SECRET_VARIABLE.search(a) for a in args)):
        return True
    if any(r.op in ("<", "<>") and _is_secret_path(r.target) for r in visit.command.redirects):
        return True
    return any(_is_secret_path(arg) for arg in _operands(program, args))


def _sends_out(visit: shell_parse.Visit) -> bool:
    """What it reads leaves the machine: a raw socket, a request body from stdin, ssh, a copy to
    another host, or a /dev/tcp redirection."""
    program, args = visit.effective[0], visit.effective[1:]
    if program in _RAW_SENDERS:
        return True
    if program in _HTTP_CLIENTS:
        return bool(_STDIN_BODY.search(" ".join(args)))
    if program == "ssh":
        return any(not a.startswith("-") for a in _operands("scp", args))
    if program in _TRANSFER_TOOLS:
        return any(_REMOTE_PATH.match(a) for a in _operands(program, args))
    return any(r.target.startswith(("/dev/tcp/", "/dev/udp/")) for r in visit.command.redirects)


def _exfil_pipeline(script: shell_parse.Script) -> bool:
    """A pipeline where a stage reads secrets and the same stage or a later one sends them out:
    `env | curl -d @- …`, `tar cz ~/.ssh | nc …`, `scp -r ~/.aws host:`, `env > /dev/tcp/…`."""
    stages: dict[int, list[shell_parse.Visit]] = {}
    for visit in shell_parse.walk(script):
        if visit.effective:
            stages.setdefault(id(visit.pipeline), []).append(visit)
    for pipeline in stages.values():
        secret_at = [v.index for v in pipeline if _reads_secrets(v)]
        for visit in pipeline:
            if secret_at and min(secret_at) <= visit.index and _sends_out(visit):
                return True
    return False


# ── Rules (Stage 1) ──────────────────────────────────────────────────────────────────────────────
# Optional keys:
#   read_only_ok      a command whose programs only read (grep, cat, git log…) does not trigger it
#   redirect_counts   with read_only_ok: a reader that redirects its output (`echo … > file`)
#                     writes, so it does trigger it
#   downgrade_when    if it returns True, a block becomes a challenge
#   payload_challenge if the match lives only inside a heredoc that nothing executes (text being
#                     composed), a block becomes a challenge
#   raw               matched against the original text: the guard's own CLI is not exempt
#   detect            a check on the parsed command (bin/shell_parse.py); `pattern` may then be None
# Each pattern is matched against the text and against what bash will run (shell_parse.normalized):
# quotes, escapes, the line's own variables, wrappers and nested code no longer hide a command.
# A hard block always wins over a challenge, wherever each one sits in this list.

BLOCK_RULES = [
    # ── Destroy ──────────────────────────────────────────────────────────────────────────────────
    {
        "id": "force_push",
        "group": "destroy",
        # --force / --force-with-lease, -f (also combined: -uf), a +branch refspec or --mirror,
        # which force-updates and deletes every remote ref. Scoped to the push's own segment: the
        # `-f` of another command on the line is not this push's.
        "pattern": (
            r"\bgit\s+push\b[^;&|\n]*"
            r"(?:\s--force(?:-with-lease)?\b|\s-[a-z]*f[a-z]*\b|\s\+\S+|\s--mirror\b)"
        ),
        "severity": "block",
        "payload_challenge": True,
        "description": "Force push rewrites shared history",
    },
    {
        "id": "git_discard",
        "group": "destroy",
        # Uncommitted work has no backup: git history cannot give it back.
        "pattern": (
            r"\bgit\s+reset\b[^;&|\n]*\s--(?:hard|merge|keep)\b"
            r"|\bgit\s+stash\s+(?:drop|clear)\b"
            r"|\bgit\s+checkout\b[^;&|\n]*\s(?:--force\b|-f\b|--\s+\.)"
            r"|\bgit\s+restore\b[^;&|\n]*\s\.(?:\s|$)"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "Throws away uncommitted work irreversibly",
    },
    {
        "id": "git_history",
        "group": "destroy",
        # What git keeps to undo a mistake: unmerged branches (-D, or -d with force), the reflog,
        # refs and unreachable objects. A merged branch (`branch -d`) loses nothing and stays.
        "pattern": (
            r"\bgit\s+(?:"
            r"branch\b[^;&|\n]*\s(?-i:-[a-zA-Z]*(?:D|d[a-zA-Z]*f|f[a-zA-Z]*d)[a-zA-Z]*)(?![\w-])"
            r"|branch\b[^;&|\n]*\s--delete\b[^;&|\n]*\s(?:--force|-f)\b"
            r"|branch\b[^;&|\n]*\s(?:--force|-f)\b[^;&|\n]*\s(?:--delete|-d)\b"
            r"|reflog\s+(?:expire|delete)\b"
            r"|update-ref\b[^;&|\n]*\s-d\b"
            r"|filter-(?:branch|repo)\b"
            r"|gc\b[^;&|\n]*\s--prune=(?:now|all)\b"
            r")"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "Destroys what git keeps to undo a mistake: unmerged branches, the reflog",
    },
    {
        "id": "find_delete",
        "group": "destroy",
        # rsync's --delete family removes whatever the source lacks; --remove-source-files the
        # source itself.
        "pattern": (
            r"\bfind\b[^;&|]*\s-delete\b|\bgit\s+clean\b"
            r"|\brsync\b[^;&|\n]*\s--(?:del|delete(?:-[a-z-]+)?|remove-source-files)\b"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "find -delete / git clean / rsync --delete: bulk removal of files",
    },
    {
        "id": "drop_database",
        "group": "destroy",
        # A DELETE whose statement ends right after the table has no WHERE: every row goes.
        "pattern": (
            r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA)\b|\bdropdb\b"
            r"|\bDELETE\s+FROM\s+[\w.\"`\[\]]+\s*(?:;|$|[\"'])"
            r"|\bFLUSH(?:ALL|DB)\b"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "Dropping a database, a schema or a table, or deleting every row",
    },
    {
        "id": "terraform_destroy",
        "group": "destroy",
        "pattern": r"\b(?:terraform|tofu)\s+(?:destroy\b|apply\b.*\s-destroy\b)",
        "severity": "block",
        "read_only_ok": True,
        "description": "terraform destroy deletes all the infrastructure in the state",
    },
    {
        "id": "kubectl_delete",
        "group": "destroy",
        "pattern": r"\bkubectl\s+delete\b|\bhelm\s+(?:uninstall|delete)\b",
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "Deleting Kubernetes resources: deleting is a human act",
    },
    {
        "id": "docker_prune",
        "group": "destroy",
        "pattern": (
            r"\bdocker\s+(?:system|container|volume|image|network|builder)\s+(?:prune|rm)\b"
            r"|\bdocker\s+(?:rmi|rm)\b"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "docker prune/rm/rmi removes containers, images or volumes irreversibly",
    },
    {
        "id": "disk_wipe",
        "group": "destroy",
        "pattern": (
            r"\bmkfs(?:\.\w+)?\b|\bwipefs\b"
            r"|\bdd\b[^;&|\n]*\bof=/dev/(?!null\b|zero\b)"
            r"|>\s*/dev/(?:sd|hd|vd|nvme|mmcblk)"
            r"|:\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"
        ),
        "severity": "block",
        "read_only_ok": True,
        "redirect_counts": True,
        "description": "Formats or overwrites a disk, or exhausts the machine",
    },
    {
        "id": "power_off",
        "group": "destroy",
        "pattern": (
            # a glob such as '*reboot*' names files, never the command
            r"(?<![\w./*-])(?:shutdown|reboot|poweroff|halt)(?![\w*-])|\b(?:tel)?init\s+[06]\b"
            # -1 as the last argument, the target, is every process the user can reach
            r"|\bkill\s+(?:-\S+\s+)*-1\s*(?:$|[;&|)\n])"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "Powers off or restarts the machine, or kills every process",
    },
    {
        "id": "rm_any",
        "group": "destroy",
        # rm and its kin on ANY path, and the same delete from inline code. `--rm` (docker run)
        # does not match, and `git rm` is exempt: git history is its backup. TRUNCATE TABLE in SQL
        # lands here too, and so does emptying a file through /dev/null. The only way to remove
        # something is bin/quarantine.py.
        "pattern": (
            r"(?<![\w-])(?<!git )(?:rm|rmdir|unlink|shred|truncate)(?![\w-])"
            r"|\bshutil\.rmtree\b|\bos\.(?:remove|removedirs)\b|\b(?:rm|unlink|rmdir)Sync\b"
            r"|\bcp\b[^;&|\n]*\s/dev/null\s+[^\s;&|]"
            r"|\bmv\b[^;&|\n]*\s/dev/null\s*(?:$|[;&|\n])"
        ),
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "description": "Deleting is a human act: use bin/quarantine.py, a reversible move",
    },
    {
        "id": "exfil_creds",
        "group": "destroy",
        # Each alternative is scoped to one segment and to what a network program really SENDS: a
        # substitution or redirect reading a credential file, a credential in a URL query, a
        # credential file piped or uploaded, or a POST with a credential word in the same segment.
        # Scoping matters: an unscoped `curl.*secret` judged the data of the next command.
        "pattern": (
            rf"(?m)\b(?:curl|wget)\b[^;|&\n]*\$\([^)\n]*(?:{_CRED_FILE}|secret)[^)\n]*\)"
            rf"|\b(?:curl|wget)\b[^;|&\n]*[?&][^\s'\";|&\n]*[a-z0-9_]*{_CRED_WORD}[a-z0-9_]*="
            rf"|\b(?:curl|wget)\b[^;|&\n]*<\s*[^\s;|&\n]*{_CRED_FILE}"
            rf"|{_CRED_FILE}[^;&\n]*\|\s*(?:sudo\s+)?(?:curl|wget)\b[^;\n]*?{_SEND_FLAG}"
            rf"|\b(?:curl|wget)\b[^;\n]*?{_SEND_FLAG}[^\n]*?@\S*{_CRED_FILE}"
            rf"|\b(?:nc|ncat|netcat|socat|scp|rsync)\b[^;|&\n]*{_CRED_FILE}"
            rf"|{_CRED_FILE}[^;&\n]*\|\s*(?:nc|ncat|netcat|socat)\b"
            rf"|^(?=[^\n;|&]*{_CRED_WORD})[^\n;|&]*?(?:\b(?:curl|wget)\b[^\n;|&]*?"
            rf"(?:-X\s+(?-i:POST)|{_SEND_FLAG})|\bhttp\s+(?-i:POST)\b)"
            rf"|\.post\s*\([^)\n;|&]*{_CRED_WORD}"
        ),
        # The parsed pipeline catches the rest: a dump of the environment or a credential folder
        # piped to a program that sends it (_exfil_pipeline).
        "detect": _exfil_pipeline,
        "severity": "block",
        "read_only_ok": True,
        "payload_challenge": True,
        "downgrade_when": _exfil_downgrade,
        "description": "Credential exfiltration through the network",
    },
    # ── Degrade security ─────────────────────────────────────────────────────────────────────────
    {
        "id": "disable_logging",
        "group": "security",
        "pattern": (
            r"--no-?log\b"
            r"|(?:stop|delete|disable)[a-z-]*(?:auditd|rsyslog|journald)\b"
            r"|(?:auditd|rsyslog|journald)[a-z-]*(?:stop|disable|delete)\b"
            r"|\bsystemctl\s+(?:stop|disable|mask)\s+(?:auditd|rsyslog|systemd-journald)\b"
            # the shell's own record of what ran
            r"|\bhistory\s+-[a-z]*c\b|\bunset\s+(?:-v\s+)?HISTFILE\b|\bHISTFILE=/dev/null\b"
            r"|\bHIST(?:FILE)?SIZE=0\b|\bset\s+\+o\s+history\b"
        ),
        "severity": "block",
        "read_only_ok": True,
        "description": "Disabling logging, the audit trail or the shell history",
    },
    {
        "id": "disable_firewall",
        "group": "security",
        "pattern": (
            r"\bufw\s+disable\b|\biptables\s+-F\b|\bnft\s+flush\s+ruleset\b|\bsetenforce\s+0\b"
            r"|\bsystemctl\s+(?:stop|disable|mask)\s+(?:ufw|firewalld|apparmor)\b"
        ),
        "severity": "block",
        "read_only_ok": True,
        "description": "Turning off the firewall or the mandatory access control",
    },
    {
        "id": "add_ssh_key",
        "group": "security",
        "pattern": r"authorized_keys|ssh-keygen.*>>",
        "severity": "challenge",
        "read_only_ok": True,
        "redirect_counts": True,
        "description": "Adding an SSH key",
    },
    {
        "id": "modify_permissions",
        "group": "security",
        "pattern": r"permissions\.yaml",
        "severity": "challenge",
        "read_only_ok": True,
        "redirect_counts": True,
        "description": "Changing the system's permission tiers",
    },
    {
        "id": "open_permissions",
        "group": "security",
        "pattern": r"\bchmod\b[^;&|\n]*\b[0-7]?777\b|\bchmod\b[^;&|\n]*\ba\+rwx\b",
        "severity": "challenge",
        "read_only_ok": True,
        "description": "Making files writable by everyone",
    },
    {
        "id": "persistence",
        "group": "security",
        "pattern": (
            r"(?:>>?|\btee\b[^;&|\n]*)\s*\S*"
            r"(?:\.bashrc|\.zshrc|\.profile|\.bash_profile|/etc/sudoers\S*|/etc/crontab)\b"
            r"|\bcrontab\s+(?!-l\b)\S|\bvisudo\b"
        ),
        "severity": "challenge",
        "read_only_ok": False,
        "description": "Changing what runs at login or on a schedule, or who can use sudo",
    },
    # ── Cross trust boundaries ───────────────────────────────────────────────────────────────────
    {
        "id": "run_cloned_code",
        "group": "trust",
        # Downloaded code reaching an interpreter that EXECUTES it: a pipe within the same pipeline
        # into an interpreter that reads its program from stdin (no script file, and no option in
        # its leading options that gives the program), or a command or process substitution.
        # Piping data into `python3 -c`, `python3 -m json.tool`, `jq` or `sha256sum` runs no
        # download. For a shell `-e` is errexit, not a program: `curl … | bash -e` runs it.
        "pattern": (
            r"\b(?:curl|wget)\b[^;&\n)]*\|\s*(?:sudo\s+(?:-\S+\s+)*)?(?:env\s+(?:\S+=\S*\s+)*)?(?:"
            r"(?:bash|sh|zsh|dash|ksh)\b(?!(?:\s+-[A-Za-z]+)*?\s+-[A-Za-z]*c[A-Za-z]*\b)"
            r"|python[0-9.]*\b(?!(?:\s+-[WX]\s*\S+|\s+-[A-Za-z]+)*?\s+-[A-Za-z]*[cm][A-Za-z]*\b)"
            r"|perl\b(?!(?:\s+-[A-Za-z]+)*?\s+-[A-Za-z]*[eE][A-Za-z]*\b)"
            r"|ruby\b(?!(?:\s+-[A-Za-z]+)*?\s+-[A-Za-z]*e[A-Za-z]*\b)"
            r"|node\b(?!(?:\s+-[A-Za-z]+)*?\s+-(?:[A-Za-z]*[ep][A-Za-z]*|-eval|-print)\b)"
            r")(?=\s*(?:$|[;&|\n)-]))"
            r"|\b(?:bash|sh|zsh|dash|ksh|python[0-9.]*)\s+-c\s+[\"']?(?:\$\(|`)\s*(?:curl|wget)\b"
            r"|\beval\s+[\"']?(?:\$\(|`)\s*(?:curl|wget)\b"
            r"|\b(?:bash|sh|zsh|dash|ksh|python[0-9.]*|source)\s+<\(\s*(?:curl|wget)\b"
            r"|(?:^|[;&|(\n]\s*|\bsudo\s+)\.\s+<\(\s*(?:curl|wget)\b"
            r"|\bpip3?\s+install\b[^;&\n]*git\+https"
            # a command that travels encoded so no rule can read it
            r"|\bbase64\s+(?:-d|-D|--decode)\b[^;&\n]*\|\s*(?:sudo\s+)?"
            r"(?:bash|sh|zsh|dash|ksh|python[0-9.]*)\b(?=\s*(?:$|[;&|\n)-]))"
        ),
        "severity": "block",
        "description": "Running code downloaded from outside or decoded from a blob",
    },
    {
        "id": "dynamic_code",
        "group": "trust",
        # The text never spells out what runs: a program name built at run time, code generated
        # for eval or source, or nesting too deep to read. Environment setup (`eval "$(ssh-agent
        # -s)"`, `source <(kubectl completion bash)`) is exempt.
        "pattern": None,
        "detect": _dynamic_code,
        "severity": "challenge",
        "description": "Runs code the command text never spells out",
    },
    {
        "id": "scan_credentials",
        "group": "trust",
        "pattern": r"find.*\.(?:ssh|netrc)\b|grep.*(?:secret|password|token).*\/(?:etc|home|var)",
        "severity": "challenge",
        "description": "Scanning the filesystem for credentials",
    },
    {
        "id": "read_secret_file",
        "group": "trust",
        # What a session reads goes to the model's provider: a secret file is not read by accident.
        "pattern": (
            r"\b(?:cat|less|more|head|tail|bat|strings|xxd|od|base64|nl)\b[^;&|\n]*?"
            rf"(?<![\w.-])(?:\S*/)?{_CRED_FILE}"
        ),
        "severity": "challenge",
        "description": "Reading a file that holds secrets into the session",
    },
    # ── Bypass review ────────────────────────────────────────────────────────────────────────────
    {
        "id": "guard_tamper",
        "group": "review",
        # An agent may not approve its own challenge nor loosen the guard. The approve CLI refuses
        # a session without a terminal too: this rule only answers earlier and clearer.
        "pattern": (
            r"auto_guard\.py\b[^;&|\n]*\sapprove\b|auto_guard_approvals\.json|auto-guard\.json"
        ),
        "severity": "block",
        "read_only_ok": True,
        "redirect_counts": True,
        "raw": True,
        "description": "Approving a challenge or changing the guard's settings is the human's",
    },
    {
        "id": "no_verify",
        "group": "review",
        # `--no-verify=false` turns the hooks back on: only the flag that skips them blocks.
        "pattern": r"--no.?verify(?!\s*=\s*(?:false|0|no)\b)|-c\s+core\.hooksPath=",
        "severity": "block",
        "description": "Skipping git hooks",
    },
    {
        "id": "hooks_path",
        "group": "review",
        # Pointing git at another hooks folder can turn the hooks off for good. Reading the
        # setting (`--get`, or the key alone) is fine.
        "pattern": (
            r"\bgit\s+config\b[^;&|\n]*?(?:"
            r"(?:--)?unset(?:-all)?\b[^;&|\n]*\bcore\.hooksPath\b"
            r"|\bcore\.hooksPath\s+(?!-)[^\s;&|]"
            r")"
        ),
        "severity": "challenge",
        "description": "Changing where git looks for its hooks can turn them off",
    },
    {
        "id": "delete_shared",
        "group": "review",
        # --delete or -d, an empty source (`:branch`) or --prune: each deletes remote branches.
        "pattern": r"\bgit\s+push\b[^;&\n]*\s(?:--delete\b|-d\b|--prune\b|:[^\s:])",
        "severity": "challenge",
        "description": "Deleting a shared remote branch",
    },
    {
        "id": "skip_verification",
        "group": "review",
        "pattern": r"--skip.?verify|--force.*deploy",
        "severity": "challenge",
        "read_only_ok": True,
        "description": "Skipping deploy verifications",
    },
    {
        "id": "prod_deploy_no_review",
        "group": "review",
        "pattern": (
            r"deploy\s+(?:to\s+)?prod\b|push\s+(?:origin\s+)?master\b|push\s+(?:origin\s+)?main\b"
        ),
        "severity": "challenge",
        "read_only_ok": True,
        "description": "Deploying or pushing straight to production without a review",
    },
    {
        "id": "force_flag",
        "group": "destroy",
        # `install --force` of a package manager is benign; `git push --force` is a block above.
        "pattern": r"(?<![\w-])(?<!install )--force(?![\w-])",
        "severity": "challenge",
        "read_only_ok": True,
        "description": "--force outside git push: ask for approval",
    },
]

# ── Denial tracking ──────────────────────────────────────────────────────────────────────────────

_MAX_CONSECUTIVE = 3
_MAX_TOTAL = 20
_denials: dict[str, int] = {}  # emitter → consecutive count
_total_denials: dict[str, int] = {}  # emitter → total count
# AUTO_GUARD_LOG lets the tests point the audit trail at a temp file.
GUARD_LOG = Path(os.environ.get("AUTO_GUARD_LOG") or (REPO_ROOT / "logs" / "auto_guard_log.jsonl"))
_LONG_TOKEN = re.compile(r"[A-Za-z0-9_\-.]{32,}")
_SENSITIVE_KEY = re.compile(
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|authorization)\s*[=:]\s*"
    r"(?:(?:bearer|basic|token)\s+)?\S+",
    re.I,
)


def _masked(text: str) -> str:
    """The text with anything that looks like a secret replaced: a blocked exfil names its secret."""
    keyed = _SENSITIVE_KEY.sub(lambda m: re.split(r"[=:]", m.group(0))[0] + "=***", text)
    return _LONG_TOKEN.sub("***", keyed)


def log_guard_event(engine: str, result: "GuardResult", command: str) -> None:
    """Append one JSONL line per block or challenge: the control to tune false positives.

    Best-effort: a failed append never changes a verdict. The hash covers the original text, so
    repeats stay detectable with the text masked.
    """
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine": engine,
        "rule": result.rule_id,
        "group": result.rule_group,
        "severity": result.action,
        "command": _masked(command)[:1000],
        "command_sha256": hashlib.sha256(command.encode("utf-8", "replace")).hexdigest(),
    }
    try:
        GUARD_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(GUARD_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as e:
        print(f"[auto_guard] could not write {GUARD_LOG}: {e}", file=sys.stderr)


def _track_denial(emitter: str, denied: bool) -> tuple[int, int]:
    """Per-process counters: the MCP server is one process per session."""
    if denied:
        _denials[emitter] = _denials.get(emitter, 0) + 1
        _total_denials[emitter] = _total_denials.get(emitter, 0) + 1
    else:
        _denials[emitter] = 0
    return _denials[emitter], _total_denials.get(emitter, 0)


# ── Human approval tokens ────────────────────────────────────────────────────────────────────────
# The way back from a challenge: the human types `bin/auto_guard.py approve <hash>` and the next
# guard() of that exact action consumes the token and allows it. It covers `challenge` only: a
# `block` means the agent never runs this, and an engine failure is not a verdict.

APPROVALS_PATH = Path(
    os.environ.get("AUTO_GUARD_APPROVALS") or (REPO_ROOT / "logs" / "auto_guard_approvals.json")
)
APPROVAL_TTL_MIN = 30  # window to use an approval


def _action_key(user_intent: str, action_text: str) -> str:
    """Identity of an approved action: exact intent plus exact action."""
    return hashlib.sha256((user_intent + "\x00" + action_text).encode("utf-8")).hexdigest()


def _read_approvals(path: Path) -> dict:
    """The {pending, approved} record. A missing or corrupt file reads as empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {"pending": {}, "approved": {}}


def _write_approvals(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps(data, ensure_ascii=False))


def _prune_expired(approved: dict, now_ts: float) -> dict:
    return {h: rec for h, rec in approved.items() if rec.get("expires", 0) > now_ts}


def record_pending_approval(user_intent: str, action_text: str, path: Path | None = None) -> str:
    """Record the challenge (hash and masked text) so the human can approve it by hash."""
    path = path or APPROVALS_PATH
    key = _action_key(user_intent, action_text)
    try:
        data = _read_approvals(path)
        data.setdefault("pending", {})[key] = {
            "action": _masked(action_text)[:500],
            "intent": _masked(user_intent)[:500],
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _write_approvals(path, data)
    except OSError as e:
        print(f"[auto_guard] could not record the pending approval: {e}", file=sys.stderr)
    return key


def approve_action(key: str, ttl_min: int = APPROVAL_TTL_MIN, path: Path | None = None) -> dict:
    """Move a pending challenge to approved with a TTL. The human runs this.

    `key` is the hash or a unique prefix of at least 8 characters. Raises KeyError when nothing
    matches.
    """
    path = path or APPROVALS_PATH
    now_ts = datetime.now(timezone.utc).timestamp()
    data = _read_approvals(path)
    pending: dict = data.get("pending") or {}
    approved: dict = _prune_expired(data.get("approved") or {}, now_ts)

    matches = [h for h in pending if h.startswith(key)] if len(key) >= 8 else []
    if len(matches) > 1:
        raise KeyError(f"ambiguous prefix: {len(matches)} pending approvals match")
    if not matches:
        raise KeyError("no pending approval for that hash: rerun the action to get a new one")
    record = pending.pop(matches[0])
    record["approved_ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    record["expires"] = now_ts + ttl_min * 60
    approved[matches[0]] = record
    _write_approvals(path, {**data, "pending": pending, "approved": approved})
    return record


def consume_approval(user_intent: str, action_text: str, path: Path | None = None) -> dict | None:
    """Return and remove the valid approval for this exact action: each one works once."""
    path = path or APPROVALS_PATH
    key = _action_key(user_intent, action_text)
    now_ts = datetime.now(timezone.utc).timestamp()
    data = _read_approvals(path)
    approved = _prune_expired(data.get("approved") or {}, now_ts)
    record = approved.pop(key, None)
    if record is None:
        return None
    _write_approvals(path, {**data, "approved": approved})
    return record


# ── Result ───────────────────────────────────────────────────────────────────────────────────────


@dataclass
class GuardResult:
    action: str  # "allow" | "challenge" | "block" | "halt"
    rule_id: str = ""
    rule_group: str = ""
    description: str = ""
    stage: int = 0  # 0 = no check needed, 1 = rule match, 2 = decision layer
    denial_count: int = 0


def auto_approve_result(result: GuardResult, action_text: str, engine: str = "auto") -> GuardResult:
    """Turn a challenge into an allow and leave the audit trail. Never called for a block.

    Each auto-approval is logged with severity "auto_approved" and the rule that would have asked:
    the control to review what went through on its own.
    """
    original = result.rule_id or "decision_layer"
    log_guard_event(
        engine or "auto",
        GuardResult(
            action=AUTO_APPROVED,
            rule_id=original,
            rule_group=result.rule_group,
            description=result.description,
            stage=result.stage,
        ),
        action_text,
    )
    return GuardResult(
        action="allow",
        rule_id=AUTO_APPROVED,
        rule_group=result.rule_group,
        description=f"auto-approved [{original}] (configs/auto-guard.json): {result.description}",
        stage=result.stage,
    )


# ── Stage 1: rules, deterministic, no LLM ────────────────────────────────────────────────────────

# Programs that only read and cannot run other commands. Deliberately absent: sed (`e`), awk
# (`system()`), rg (`--pre`), sort (`--compress-program`), find (`-exec`), xargs.
_READ_ONLY_PROGRAMS = frozenset(
    {
        "grep",
        "egrep",
        "fgrep",
        "cat",
        "head",
        "tail",
        "wc",
        "ls",
        "echo",
        "printf",
        "pwd",
        "cd",
        "true",
    }
)
_READ_ONLY_GIT = frozenset({"grep", "log", "show"})
# Manual pages only read, unless an option or the environment names a program to show them with.
_DOC_PROGRAMS = frozenset({"man", "whatis", "apropos"})
_DOC_RUNNER_OPTION = re.compile(r"^(?:--pager|--html|-[A-Za-z]*[PH])")
_DOC_RUNNER_VARS = frozenset({"MANPAGER", "PAGER", "BROWSER", "MANOPT"})
_GIT_EXEC_FLAGS = ("--ext-diff", "--textconv")  # they run external diff or filter programs
_SEGMENT_OPERATORS = frozenset({"|", "||", "&&", ";", "&", "|&"})
# Newlines, substitutions and network redirections hide other commands.
_NOT_READ_ONLY_MARKERS = ("\n", "`", "$(", "<(", ">(", "/dev/tcp", "/dev/udp")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `>`, `>>` or `>|` toward anything but the null device, stdout, stderr or another descriptor.
_OUTPUT_REDIRECT = re.compile(r"(?<![<&])>{1,2}\|?\s*(?!&|/dev/(?:null|stdout|stderr)\b)\S")


def _segment_only_reads(words: list[str]) -> bool:
    """Whether one pipeline segment (its words, without operators) runs a read-only program."""
    assigned = set()
    while words and _ASSIGNMENT.match(words[0]):
        assigned.add(words[0].split("=", 1)[0])
        words = words[1:]  # VAR=value prefixes
    if not words:
        return True
    program = words[0].rsplit("/", 1)[-1]
    if program in _DOC_PROGRAMS:
        return not (assigned & _DOC_RUNNER_VARS) and not any(
            _DOC_RUNNER_OPTION.match(word) for word in words[1:]
        )
    if program == "git":
        return (
            len(words) > 1
            and words[1] in _READ_ONLY_GIT
            and not any(word.startswith(_GIT_EXEC_FLAGS) for word in words[2:])
        )
    return program in _READ_ONLY_PROGRAMS


def _is_read_only(command: str) -> bool:
    """Whether every program in a shell command only reads (grep, cat, git log…).

    Lets execution rules ignore searches that merely mention them. Fail-closed: a newline, a
    substitution, /dev/tcp or /dev/udp, or unbalanced quotes make the command not read-only.
    """
    if not command.strip() or any(marker in command for marker in _NOT_READ_ONLY_MARKERS):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        # shlex opens a comment at a `#` inside a word, bash only at a word's start: `grep x#; curl
        # …` read as one grep. Every word is kept: a real comment only costs a stricter verdict.
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return False
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEGMENT_OPERATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return all(_segment_only_reads(segment) for segment in segments)


# A segment that invokes the guard's own CLI: the quoted command is the ARGUMENT being evaluated,
# never something the shell runs. Only the exact invocation is exempt: argv parsed with shlex, and
# no `$`, backtick, `<` or `>` anywhere in the segment, so whatever the shell would execute keeps
# being judged.
_HEREDOC_START = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
_PY_PROG = re.compile(r"^(?:\S*/)?python[23]?(?:\.\d+)?$")
_SELF_TEST_PROG = re.compile(r"^(?:\S+/)?auto_guard\.py$")
_SELF_TEST_PY_FLAGS = frozenset({"-I", "-O", "-OO", "-B", "-E", "-S", "-u", "-W"})
# A heredoc feeding a shell runs its body verbatim: its payload is an action, never text. A
# non-shell interpreter runs code in another language, where a shell command is quoted data.
_HEREDOC_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "su", "eval", "source", "xargs"})


def _is_exact_self_test(segment: str) -> bool:
    seg = segment.strip()
    if not seg or any(ch in seg for ch in "$`><"):
        return False
    try:
        tokens = shlex.split(seg)
    except ValueError:
        return False
    if not tokens:
        return False
    if _SELF_TEST_PROG.match(tokens[0]):
        return True
    if not _PY_PROG.match(tokens[0]):
        return False
    rest = tokens[1:]
    while rest and rest[0] in _SELF_TEST_PY_FLAGS:
        rest = rest[1:]
    return bool(rest) and _SELF_TEST_PROG.match(rest[0]) is not None


# The message of a commit or a tag is text the command records, never something it runs:
# `git commit -m "explain why rm -rf / is blocked"` deletes nothing. Only a plain quoted message
# is masked; one with a substitution in it still runs that substitution, and stays visible.
_GIT_MESSAGE = re.compile(
    r"(\bgit\s+(?:commit|tag)\b[^;&|\n]*?\s(?:-m|--message)(?:=|\s+))" r"(\"[^\"$`\\]*\"|'[^']*')"
)


def _strip_guard_self_tests(action_text: str) -> str:
    # `2>&1 | head` on the guard's own output is harmless, and its `&` would split the segment
    # before the exact-form check sees it.
    action_text = _GIT_MESSAGE.sub(r'\1"message"', action_text.replace("2>&1", " "))
    parts = re.split(r"([;&|\n]+)", action_text)
    return "".join(";" if _is_exact_self_test(p) else p for p in parts)


def _heredoc_span(action_text: str) -> tuple[int, int, bool] | None:
    """(body_start, body_end, consumer_executes) of the first heredoc, or None.

    The terminator line closes the span, so a command after it never rides the downgrade. An
    unterminated heredoc gets no downgrade either.
    """
    m = _HEREDOC_START.search(action_text)
    if not m:
        return None
    term = re.escape(m.group(1))
    end_m = re.search(rf"^[ \t]*{term}[ \t]*$", action_text[m.end() :], re.MULTILINE)
    if not end_m:
        return None
    body_start, body_end = m.end(), m.end() + end_m.start()
    consumer = (
        action_text[: m.start()]
        .rsplit(";", 1)[-1]
        .rsplit("&&", 1)[-1]
        .rsplit("||", 1)[-1]
        .rsplit("|", 1)[-1]
        .strip()
    )
    words = consumer.split()
    while words and "=" in words[0] and not words[0].startswith(("-", "/")):
        words = words[1:]
    if words and words[0] == "sudo":
        words = words[1:]
    prog = words[0].rsplit("/", 1)[-1] if words else ""
    executes = (
        prog in _HEREDOC_SHELLS or re.search(r"\bkubectl\s+\S.*\bexec\b", consumer) is not None
    )
    return body_start, body_end, executes


def _downgraded_description(rule: dict, text: str) -> str:
    """Why a matched block becomes a challenge, or "" when it stays a block."""
    pattern = rule.get("pattern")
    if pattern and rule.get("payload_challenge"):
        span = _heredoc_span(text)
        # the text must match inside the body: a hit from the parsed command alone is code
        if (
            span is not None
            and not span[2]
            and re.search(pattern, text[span[0] : span[1]], re.IGNORECASE)
            and not (
                re.search(pattern, text[: span[0]], re.IGNORECASE)
                or re.search(pattern, text[span[1] :], re.IGNORECASE)
            )
        ):
            return " (challenge: match only inside a heredoc payload)"
    if rule.get("downgrade_when") and rule["downgrade_when"](text):
        return " (challenge: loopback, local auth or test credential)"
    return ""


# Inline Python that can reach nothing outside itself: no import beyond these, no name or attribute
# that opens, runs, deletes or sends.
_INERT_MODULES = frozenset(
    {
        "json",
        "math",
        "re",
        "sys",
        "datetime",
        "time",
        "random",
        "string",
        "textwrap",
        "itertools",
        "collections",
        "functools",
        "statistics",
        "decimal",
        "fractions",
        "hashlib",
        "uuid",
        "base64",
        "binascii",
        "pprint",
        "operator",
        "enum",
        "dataclasses",
        "typing",
        "unicodedata",
        "calendar",
        "bisect",
        "heapq",
        "copy",
        "numbers",
        "zlib",
        "struct",
    }
)
_RISKY_NAMES = frozenset(
    {
        "eval",
        "exec",
        "compile",
        "__import__",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "breakpoint",
        "input",
    }
)
_RISKY_ATTRS = frozenset(
    {
        "system",
        "popen",
        "fork",
        "kill",
        "remove",
        "removedirs",
        "unlink",
        "rmdir",
        "rmtree",
        "rename",
        "renames",
        "replace",
        "truncate",
        "write",
        "write_text",
        "write_bytes",
        "writelines",
        "chmod",
        "chown",
        "symlink",
        "link",
        "modules",
        "run",
        "call",
        "check_call",
        "check_output",
        "Popen",
        "getoutput",
        "getstatusoutput",
        "urlopen",
        "urlretrieve",
        "connect",
        "send",
        "sendall",
        "sendto",
    }
)
_PYTHON = re.compile(r"^python[0-9.]*$")
_OUTPUT_OPS = frozenset({">", ">>", ">|", "&>", "&>>", "<>"})


def _inert_python(code: str) -> bool:
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name.split(".")[0] not in _INERT_MODULES for alias in node.names):
                return False
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in _INERT_MODULES:
                return False
        elif isinstance(node, ast.Name):
            if node.id in _RISKY_NAMES or node.id.startswith("__"):
                return False
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith("_") or attr in _RISKY_ATTRS or attr.startswith(("spawn", "exec")):
                return False
    return True


def _python_code_word(words: list[shell_parse.Word]) -> shell_parse.Word | None:
    """The CODE of `python3 [options] -c CODE`, or None for a script, a module or stdin."""
    for i, word in enumerate(words[1:], start=1):
        text = word.text
        if text == "-c" or re.fullmatch(r"-[A-Za-z]+c", text):
            return words[i + 1] if i + 1 < len(words) else None
        if not text.startswith("-") or text in ("-", "--") or text.startswith(("-m", "-c")):
            return None
        if text in ("-W", "-X"):
            return None  # an option value would be misread as the code; leave it to the rules
    return None


def _mask_inert_python(text: str, script: shell_parse.Script) -> str:
    """`python3 -c 'print("shutdown")'` prints a word and runs nothing. Its code is masked, as a
    commit message is, when it can reach nothing outside itself and its output only reaches the
    terminal: last in its pipeline, not redirected, not inside a substitution or a group."""
    if script.errors:
        return text
    spans: list[tuple[int, int]] = []
    for visit in shell_parse.walk(script):
        if not visit.effective or not _PYTHON.match(visit.effective[0]):
            continue
        if not any(p is visit.pipeline for p in script.pipelines):
            continue
        if visit.index != len(visit.pipeline.commands) - 1:
            continue
        if any(
            r.op in _OUTPUT_OPS or (r.op == ">&" and not re.fullmatch(r"\d+|-", r.target))
            for r in visit.command.redirects
        ):
            continue
        code = _python_code_word(visit.words)
        if code is not None and code.exact and _inert_python(code.text):
            spans.append((code.start, code.end))
    for start, end in sorted(spans, reverse=True):
        text = text[:start] + '"code"' + text[end:]
    return text


def _views(action_text: str) -> tuple[str, str, shell_parse.Script]:
    """(the text, with self-tests, commit messages and inert code masked; what bash will run;
    the parsed command)."""
    stripped = _strip_guard_self_tests(action_text)
    script = shell_parse.parse(stripped)
    masked = _mask_inert_python(stripped, script)
    if masked != stripped:
        stripped, script = masked, shell_parse.parse(masked)
    return stripped, shell_parse.normalized(script), script


def _fires(rule: dict, text: str, normalized: str, script: shell_parse.Script | None) -> bool:
    pattern = rule.get("pattern")
    if pattern and (
        re.search(pattern, text, re.IGNORECASE)
        or (normalized and re.search(pattern, normalized, re.IGNORECASE))
    ):
        return True
    detect = rule.get("detect")
    return bool(detect and script is not None and detect(script))


def check_block_rules(action_text: str) -> GuardResult | None:
    """Stage 1: match every rule. None when the action passes clean.

    A downgraded or designated challenge keeps scanning: a later rule may hard-block the same
    command, so a challenge on a heredoc's text cannot mask an exfil after its terminator.
    """
    stripped, normalized, script = _views(action_text)
    raw_normalized = ""
    pending: GuardResult | None = None
    for rule in BLOCK_RULES:
        if rule.get("raw"):
            # the guard's own CLI is not exempt here, and quotes still cannot hide a word from it
            raw_normalized = raw_normalized or shell_parse.normalized(
                shell_parse.parse(action_text)
            )
            text, view, tree = action_text, raw_normalized, None
        else:
            text, view, tree = stripped, normalized, script
        if not _fires(rule, text, view, tree):
            continue
        if (
            rule.get("read_only_ok")
            and _is_read_only(text)
            and not (rule.get("redirect_counts") and _OUTPUT_REDIRECT.search(text))
        ):
            continue
        action = rule["severity"]
        description = rule["description"]
        if action == "block":
            downgrade = _downgraded_description(rule, text)
            if downgrade:
                action = "challenge"
                description += downgrade
        hit = GuardResult(
            action=action,
            rule_id=rule["id"],
            rule_group=rule["group"],
            description=description,
            stage=1,
        )
        if action == "block":
            return hit
        pending = pending or hit
    return pending


# ── Stage 2: decision layer, optional ────────────────────────────────────────────────────────────

ENGINE_UNAVAILABLE = "engine_unavailable"


def check_decision_layer(user_intent: str, action_text: str, _ask=None) -> GuardResult:
    """Stage 2: the decision layer judges an action Stage 1 did not flag.

    Reasoning-blind: it sees only user_intent and action_text. An engine without an answer gets
    one retry; if it persists the result is a challenge with rule_id=engine_unavailable, which is
    not a verdict on the action.
    """
    state = {"user_request": user_intent[:500], "proposed_action": action_text[:500]}
    last_error = ""
    for attempt in (1, 2):
        try:
            sys.path.insert(0, str(REPO_ROOT / "bin"))
            from decision_integrations import guard_mutation

            result = guard_mutation(state, _ask=_ask)
            if result.get("engine_ok", True):
                return GuardResult(
                    action=result["action"],
                    rule_id="decision_layer",
                    description="; ".join(result.get("reasons", [])),
                    stage=2,
                )
            last_error = "; ".join(result.get("reasons", [])) or "no usable answer"
        except Exception as e:  # pylint: disable=broad-except
            last_error = f"{type(e).__name__}: {e}"
        print(
            f"[auto_guard] stage 2 engine failure (attempt {attempt}/2): {last_error}",
            file=sys.stderr,
        )
    return GuardResult(
        action="challenge",
        rule_id=ENGINE_UNAVAILABLE,
        description=f"engine unavailable: {last_error[:200]}",
        stage=2,
    )


# ── The guard ────────────────────────────────────────────────────────────────────────────────────

# No automated judgment ever authorizes a delete. CLI verbs are Stage 1's; this catches the rest,
# natural-language actions that reach Stage 2 clean. Matched against the action text only.
_DELETE_SHAPED_RE = re.compile(
    r"(?i)\b(?:delete[ds]?|destroy(?:ed)?|terminate[ds]?|tear\s?down|wipe[ds]?|"
    r"purge[ds]?|prun(?:e|ed|ing)|"
    r"borra[dr]|borrando|eliminar?|eliminando|destruir|destruido|destruida)\b"
)


def _is_delete_shaped(action_text: str) -> bool:
    """Whether the action deletes or destroys something, as a CLI verb or in plain words."""
    return _DELETE_SHAPED_RE.search(action_text) is not None


def guard(
    user_intent: str,
    action_text: str,
    emitter: str = "orchestrator",
    _ask=None,
    _stage2=None,
    approvals_path: Path | None = None,
    use_stage2: bool = True,
    log_engine: str = "",
    auto_approve: bool | None = None,
) -> GuardResult:
    """Judge a mutation BEFORE it runs.

    Stage 1 always runs. Stage 2 runs when it was not turned off for this call and the engine has
    a key. With no rule match and no objection, allow: these rules are the first line, not the
    only one.
    log_engine: when set, every denial lands in the audit log (--log-stats reports it).
    auto_approve: None reads configs/auto-guard.json; False forces the human-token semantics.
    """
    stage1 = check_block_rules(action_text)
    if stage1:
        result = stage1
    elif _stage2 is not None:
        result = _stage2
    elif use_stage2 and (_ask is not None or stage2_enabled()):
        result = check_decision_layer(user_intent, action_text, _ask)
    else:
        result = GuardResult(action="allow", stage=0)

    if result.stage == 2:
        log_guard_event("stage2", result, action_text)

    settings = auto_approve_settings()
    auto = settings["enabled"] if auto_approve is None else auto_approve

    if result.rule_id == ENGINE_UNAVAILABLE:
        if auto and ENGINE_UNAVAILABLE in settings["applies_to"]:
            return auto_approve_result(result, action_text, log_engine or emitter)
        return result  # not a verdict: it neither counts toward nor resets the halt

    # The veto runs after the engine-failure return on purpose: a failure is not a verdict, and a
    # Stage 1 result never reaches here as an allow.
    if (
        result.stage == 2
        and result.action in ("allow", "challenge")
        and _is_delete_shaped(action_text)
    ):
        result = GuardResult(
            action="block",
            rule_id="delete_human_only",
            rule_group="destroy",
            description=(
                f"decision layer said {result.action}, vetoed: a delete is never authorized "
                "automatically (use bin/quarantine.py)"
            ),
            stage=2,
        )
        log_guard_event("stage2", result, action_text)

    approvals = approvals_path or APPROVALS_PATH
    if result.action == "challenge":
        if auto:
            result = auto_approve_result(result, action_text, log_engine or emitter)
        else:
            approval = consume_approval(user_intent, action_text, approvals)
            if approval:
                result = GuardResult(
                    action="allow",
                    description=(
                        f"human approval consumed (approved {approval.get('approved_ts', '?')})"
                    ),
                    stage=result.stage,
                )
            else:
                record_pending_approval(user_intent, action_text, approvals)

    denied = result.action in ("block", "challenge", "halt")
    if log_engine and denied and result.stage != 2:
        log_guard_event(log_engine, result, action_text)
    consecutive, total = _track_denial(emitter, denied)

    if denied:
        result.denial_count = consecutive
        if consecutive >= _MAX_CONSECUTIVE or total >= _MAX_TOTAL:
            result.action = "halt"
            result.description = (
                f"HALT: {consecutive} consecutive / {total} total denials: escalate to the human"
            )

    return result


def guard_response(
    result: GuardResult, user_intent: str = "", action_text: str = ""
) -> dict[str, Any]:
    """The structured answer for the agent. With both texts, a challenge carries `approve`: the
    hash and the exact command the human types to approve that action."""
    if result.action == "allow":
        if result.rule_id == AUTO_APPROVED:
            return {
                "allowed": True,
                "auto_approved": True,
                "rule": AUTO_APPROVED,
                "description": result.description,
            }
        return {"allowed": True}

    if result.rule_id == ENGINE_UNAVAILABLE:
        instruction = (
            "The guard could not evaluate this action (decision engine unavailable). "
            "Do not proceed on your own: retry later or ask the human."
        )
    elif result.action == "halt":
        instruction = (
            "HALT: too many blocked attempts. Escalating to the human. "
            "Do not attempt further mutations in this session."
        )
    elif result.action == "challenge":
        instruction = (
            "This action needs the human's explicit approval. Ask the human first. "
            "Do NOT rephrase or split it to get past the guard."
        )
    else:
        instruction = (
            "Agents never run this action. Find a safer path or ask the human to run it. "
            "Do NOT try to route around this block."
        )

    response = {
        "allowed": False,
        "action": result.action,
        "rule": result.rule_id,
        "group": result.rule_group,
        "description": result.description,
        "stage": result.stage,
        "denial_count": result.denial_count,
        "engine_ok": result.rule_id != ENGINE_UNAVAILABLE,
        "instruction": instruction,
    }
    if result.action == "challenge" and result.rule_id != ENGINE_UNAVAILABLE and action_text:
        approve_hash = _action_key(user_intent, action_text)
        response["approve"] = {
            "hash": approve_hash,
            "cmd": f"{APPROVE_CMD} {approve_hash[:16]}",
            "note": "the HUMAN runs this in a terminal; the next try of this exact action uses it",
        }
    return response


def _reset_counters() -> None:
    _denials.clear()
    _total_denials.clear()


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────


def status() -> dict[str, Any]:
    """What is on: the machine-readable state `pak doctor` reports."""
    settings = auto_approve_settings()
    stage2 = stage2_enabled()
    return {
        "stage1": {"state": "on", "rules": len(BLOCK_RULES)},
        "stage2": {
            "state": "on" if stage2 else "off",
            "detail": "" if stage2 else "OPENROUTER_API_KEY is not set: challenges ask the human",
        },
        "auto_approve": settings["enabled"],
    }


def log_stats(last: int = 20) -> int:
    """Which rule fires, how often, with examples: the control to tune false positives."""
    events = []
    if GUARD_LOG.exists():
        with open(GUARD_LOG, encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    if not events:
        print(f"no denials logged yet ({GUARD_LOG})")
        return 0
    from collections import Counter

    by_rule = Counter((e.get("rule") or "?", e.get("engine") or "?") for e in events)
    print(f"=== auto-guard log: {len(events)} events ({GUARD_LOG}) ===\n")
    print(f"{'rule':24} {'engine':9} count")
    for (rule, engine), count in by_rule.most_common():
        print(f"{rule:24} {engine:9} {count}")
    print(f"\n--- last {min(last, len(events))} events ---")
    for e in events[-last:]:
        print(
            f"{e.get('ts', '?')} [{e.get('engine', '?')}] {e.get('rule', '?'):20} "
            f"{e.get('command', '')[:100]}"
        )
    return 0


def cmd_approve(key: str, ttl_min: int) -> int:
    """`approve <hash>`: only a human at a terminal. A tool call has no terminal."""
    if not sys.stdin.isatty():
        print("approve needs a terminal: the human runs this, an agent never does", file=sys.stderr)
        return 2
    try:
        record = approve_action(key=key, ttl_min=ttl_min)
    except KeyError as e:
        print(f"nothing to approve: {e.args[0]}", file=sys.stderr)
        return 1
    print(f"approved for {ttl_min} min: {record.get('action', '?')[:120]}")
    return 0


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=f"Auto-guard: the shared rules ({PROTOCOL})")
    ap.add_argument("action", nargs="?", help="the action or command to judge, or `approve`")
    ap.add_argument("key", nargs="?", help="with `approve`: the hash or a prefix of 8 or more")
    ap.add_argument("--intent", default="", help="what the user asked for")
    ap.add_argument("--stdin", action="store_true", help="read the action from stdin")
    ap.add_argument("--stage1-only", action="store_true", help="rules only: what the hooks use")
    ap.add_argument("--json", action="store_true", help="one-line JSON output")
    ap.add_argument("--engine", default="cli", help="who is calling: it lands in the audit log")
    ap.add_argument("--log-stats", action="store_true", help="report the logged denials")
    ap.add_argument("--status", action="store_true", help="print what is on, as JSON")
    ap.add_argument("--strict", action="store_true", help="ignore auto-approval for this call")
    ap.add_argument("--ttl-min", type=int, default=APPROVAL_TTL_MIN, help="approve: minutes valid")
    args = ap.parse_args()

    if args.log_stats:
        return log_stats()
    if args.status:
        print(json.dumps(status(), ensure_ascii=False))
        return 0
    if args.action == "approve":
        return cmd_approve(args.key or "", args.ttl_min)
    action = sys.stdin.read() if args.stdin else args.action
    if not action:
        ap.error("missing the action to judge (or use approve <hash>, --log-stats, --status)")

    result = guard(
        args.intent,
        action,
        use_stage2=not args.stage1_only,
        log_engine=args.engine,
        auto_approve=False if args.strict else None,
    )
    resp = guard_response(result, args.intent, action)
    if args.json:
        print(json.dumps(resp, ensure_ascii=False))
    elif resp["allowed"]:
        print("allow")
    else:
        print(
            f"{resp['action']} · {resp['rule'] or '-'} · {resp['description']}\n{resp['instruction']}"
        )
    return 0 if result.action == "allow" else 1


if __name__ == "__main__":
    sys.exit(main())
