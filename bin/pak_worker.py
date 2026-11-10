#!/usr/bin/env python3
"""pak_worker.py — work without supervision, and nothing lands without review.

A task goes from the queue to a reviewed patch, never to a commit:

  1. a throwaway clone of the repository (`git clone --local`): the agent never touches the real
     working tree, and no branch is created there
  2. Claude Code, headless, in that clone, inside a container (bin/worker/Dockerfile): no network
     but the model API (bin/egress.py), a read-only root, no capabilities, and nothing mounted but
     the clone, the task's own HOME and the kit's guards. The guards still judge every command and
     write, and `--max-budget-usd` caps the spend. `--isolation host` runs it on this machine
     instead, with the environment filtered to an allowlist and the guards as the only line
  3. the change is taken as a patch (`git diff`), never committed
  4. a second, independent call, with no tools and in an empty folder, judges the patch against
     the task: approve or reject
  5. the human applies an approved patch, if they want it: `git apply <patch>`

The container needs Docker and ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN (`claude setup-token`):
without them a task refuses to run and says so, it never falls back to the host.

Tasks live in ~/.pak/tasks/<id>/ (PAK_TASKS_DIR overrides it): task.json, patch.diff, verdict.json,
the logs of both calls, the container's HOME and egress.jsonl, every connection it asked for.

Usage:
  bin/pak_worker.py add "fix the failing test in utils/" --repo ~/code/app [--budget 1.50]
                    [--isolation host]
  bin/pak_worker.py run [ID]       # the oldest queued task, or this one
  bin/pak_worker.py status [ID]    # one task, or the list
  bin/pak_worker.py image          # build the container image (run builds it when missing)
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import egress

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_BUDGET_USD = 1.0
JUDGE_SHARE = 0.25  # of the budget, for the review call
RUN_TIMEOUT_S = 1800
GIT_TIMEOUT_S = 300
MAX_PATCH_CHARS = 60000  # what the judge reads of a patch
# What reaches the headless engine from this environment: enough to run and to reach its model,
# nothing else. A secret exported in the shell for another tool stays out.
ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "TERM",
    "TMPDIR",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "XDG_CACHE_HOME",
    "XDG_STATE_HOME",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "DISABLE_AUTOUPDATER",
    "MEMORY_SERVICE_URL",
)
ISOLATIONS = ("container", "host")
# What the engine in the container can log in with: never the human's login on this machine.
CREDENTIALS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")
DOCKERFILE = REPO_ROOT / "bin" / "worker" / "Dockerfile"
CLAUDE_CODE_VERSION = REPO_ROOT / "configs" / "claude-code.version"
# What the container sees of the kit: the guards and what they read. Never its root, where .env
# and the logs live.
KIT_PARTS = ("bin", "configs", "local/hooks", "protocols")
KIT, WORK, HOME, SOCKETS = "/pak", "/work", "/task/home", "/run/pak"
CONTAINER_LIMITS = ("--pids-limit", "512", "--memory", "4g", "--cpus", "2")
DOCKER_TIMEOUT_S = 30
BUILD_TIMEOUT_S = 1800
PROXY_URL = f"http://{egress.PROXY_LISTEN}"
# The engine's environment inside the container. Secrets are not here: they travel by name.
CONTAINER_ENV = {
    "HOME": HOME,
    "HTTPS_PROXY": PROXY_URL,
    "https_proxy": PROXY_URL,
    "HTTP_PROXY": PROXY_URL,
    "http_proxy": PROXY_URL,
    "NO_PROXY": "127.0.0.1,localhost",
    "no_proxy": "127.0.0.1,localhost",
    "DISABLE_AUTOUPDATER": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "AUTO_GUARD_LOG": f"{HOME}/.pak/auto_guard_log.jsonl",
    "AUTO_GUARD_APPROVALS": f"{HOME}/.pak/auto_guard_approvals.json",
    "PYTHONDONTWRITEBYTECODE": "1",
}
PASSED_BY_VALUE = ("ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "LANG", "TERM")
WORKER_ARGS = ("--permission-mode", "bypassPermissions")
# The review reads the patch in its prompt: it needs no tool, so a patch that talks to it can
# make it run nothing.
JUDGE_ARGS = ("--tools", "")
WORKER_PROMPT = """You are working alone on this task, in a throwaway copy of the repository. Nobody
will answer questions: decide with the conventions the repository already has. Make the change,
run the project's tests if it has them, and stop. Never commit, never push: your change is taken
as a patch and reviewed.

Task: {task}"""
JUDGE_PROMPT = """You review a patch an autonomous agent wrote for a task. Approve it only if it
does what the task asks, does nothing else, and breaks nothing you can see. Answer with ONE line
of JSON and nothing else: {{"verdict": "approve" or "reject", "reasons": ["…"]}}

Task: {task}

Patch:
{patch}"""


def tasks_dir() -> Path:
    return Path(os.environ.get("PAK_TASKS_DIR") or Path.home() / ".pak" / "tasks")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _save(task: dict) -> dict:
    folder = tasks_dir() / task["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "task.json").write_text(json.dumps(task, indent=2) + "\n", encoding="utf-8")
    return task


def load(task_id: str) -> dict:
    path = tasks_dir() / task_id / "task.json"
    if not path.exists():
        raise KeyError(f"no task {task_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def all_tasks() -> list[dict]:
    if not tasks_dir().exists():
        return []
    tasks = [json.loads(p.read_text(encoding="utf-8")) for p in tasks_dir().glob("*/task.json")]
    return sorted(tasks, key=lambda t: t["created"])


def add(
    prompt: str,
    repo: str,
    budget: float = DEFAULT_BUDGET_USD,
    isolation: str = "container",
) -> dict:
    root = Path(repo).expanduser().resolve()
    if not prompt.strip():
        raise ValueError("a task needs a prompt")
    if not (root / ".git").exists():
        raise ValueError(f"{root} is not a git repository")
    if budget <= 0:
        raise ValueError("the budget must be positive")
    if isolation not in ISOLATIONS:
        raise ValueError(f"isolation is container or host, not {isolation!r}")
    task = {
        "id": uuid.uuid4().hex[:10],
        "prompt": prompt.strip(),
        "repo": str(root),
        "budget_usd": budget,
        "isolation": isolation,
        "status": "queued",
        "created": _now(),
    }
    return _save(task)


def filtered_env(env=None) -> dict[str, str]:
    env = os.environ if env is None else env
    return {key: env[key] for key in ENV_ALLOWLIST if key in env}


# ── the container ────────────────────────────────────────────────────────────────────────────────


@dataclass
class Container:
    """Where an isolated task's engine runs: the name its runs take, its HOME, its socket folder."""

    name: str
    home: Path
    sockets: Path


def _docker(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        capture_output=True,
        text=True,
        timeout=DOCKER_TIMEOUT_S,
        check=False,
    )


def claude_code_version() -> str:
    version = CLAUDE_CODE_VERSION.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError(f"{CLAUDE_CODE_VERSION} must hold one exact version, like 2.1.263")
    return version


def image_tag() -> str:
    """pak-worker:<Claude Code version>-<first 8 of the Dockerfile's sha256>: never latest, and a
    changed Dockerfile is a new image."""
    digest = hashlib.sha256(DOCKERFILE.read_bytes()).hexdigest()[:8]
    return f"pak-worker:{claude_code_version()}-{digest}"


def container_problem(env=None) -> str:
    """Why a task cannot run in its container here, or "" when it can."""
    env = os.environ if env is None else env
    if not shutil.which("docker"):
        return (
            "Docker is not installed (INSTALL.md). To run the task on this machine instead, with "
            "the guards as the only line, queue it again with --isolation host"
        )
    try:
        answers = _docker("info", "--format", "{{.ServerVersion}}").returncode == 0
    except subprocess.TimeoutExpired:
        answers = False
    if not answers:
        return "Docker does not answer (docker info): start it and run the task again"
    if not any(env.get(key) for key in CREDENTIALS):
        return (
            "the container needs ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN from "
            "`claude setup-token`: your login on this machine does not reach it"
        )
    try:
        egress.allowlist(env)
    except ValueError as e:
        return f"the container's way out cannot be set from PAK_WORKER_EGRESS or ANTHROPIC_BASE_URL: {e}"
    return ""


def image_present() -> bool:
    return _docker("image", "inspect", image_tag()).returncode == 0


def build_image() -> str:
    tag = image_tag()
    command = ["docker", "build", "--tag", tag, "--file", str(DOCKERFILE)]
    command += [
        "--build-arg",
        f"CLAUDE_CODE_VERSION={claude_code_version()}",
        str(DOCKERFILE.parent),
    ]
    try:
        code = subprocess.run(command, timeout=BUILD_TIMEOUT_S, check=False).returncode
    except subprocess.TimeoutExpired as e:
        raise ValueError(f"docker build of {tag} did not end in {BUILD_TIMEOUT_S} s") from e
    if code != 0:
        raise ValueError(f"docker build of {tag} failed (exit {code})")
    return tag


def guard_settings() -> dict:
    """The container's ~/.claude/settings.json: the PreToolUse hooks the installer registers
    (local/hooks/install-hooks.py), at their paths under /pak, and nothing else."""
    path = REPO_ROOT / "local" / "hooks" / "install-hooks.py"
    spec = importlib.util.spec_from_file_location("install_hooks", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot read the hooks to install from {path}")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    groups: dict[str, list] = {}
    for event, matcher, command, timeout in installer.MANAGED:
        if event == "PreToolUse":
            inside = f"{KIT}/{Path(command).relative_to(REPO_ROOT).as_posix()}"
            groups.setdefault(matcher, []).append(
                {"type": "command", "command": inside, "timeout": timeout}
            )
    return {"hooks": {"PreToolUse": [{"matcher": m, "hooks": h} for m, h in groups.items()]}}


def _prepare_home(folder: Path) -> Path:
    home = folder / "home"
    (home / ".claude").mkdir(parents=True, exist_ok=True)
    (home / ".pak").mkdir(exist_ok=True)
    settings = json.dumps(guard_settings(), indent=2) + "\n"
    (home / ".claude" / "settings.json").write_text(settings, encoding="utf-8")
    return home


@contextmanager
def _isolated(task: dict, folder: Path):
    """The task's container, with its way out open while the task runs; None on the host."""
    if task.get("isolation", "container") != "container":
        yield None
        return
    # a unix socket's path must stay short: it lives in a private temporary folder of its own
    with tempfile.TemporaryDirectory(prefix="pak-egress-") as sockets:
        proxy = egress.serve_proxy(
            Path(sockets) / "egress.sock", egress.allowlist(), folder / "egress.jsonl"
        )
        try:
            yield Container(f"pak-task-{task['id']}", _prepare_home(folder), Path(sockets))
        finally:
            proxy.shutdown()
            proxy.server_close()


def container_command(
    name: str, work: Path, container: Container, claude_args: list[str], env=None
) -> list[str]:
    """The `docker run` of one engine call: no network but the bridge to the host's proxy."""
    env = os.environ if env is None else env
    argv = ["docker", "run", "--rm", "--init", "--name", name, "--network", "none"]
    argv += ["--read-only", "--tmpfs", "/tmp", "--cap-drop", "ALL"]
    argv += ["--security-opt", "no-new-privileges", *CONTAINER_LIMITS]
    argv += ["--user", f"{os.getuid()}:{os.getgid()}", "--workdir", WORK]
    mounts = [
        (work, WORK, ""),
        (container.home, HOME, ""),
        (container.sockets, SOCKETS, ""),
    ]
    mounts += [(REPO_ROOT / part, f"{KIT}/{part}", ",readonly") for part in KIT_PARTS]
    for source, target, mode in mounts:
        argv += ["--mount", f"type=bind,source={source},target={target}{mode}"]
    for key, value in CONTAINER_ENV.items():
        argv += ["--env", f"{key}={value}"]
    argv += [a for key in PASSED_BY_VALUE if env.get(key) for a in ("--env", f"{key}={env[key]}")]
    # a secret goes by name: docker copies its value, which never shows in the process list
    argv += [a for key in CREDENTIALS if env.get(key) for a in ("--env", key)]
    argv += [image_tag(), "python3", f"{KIT}/bin/egress.py", "bridge"]
    argv += ["--socket", f"{SOCKETS}/egress.sock"]
    argv += [a for where in egress.forwards(env) for a in ("--forward", where)]
    return [*argv, "--", "claude", *claude_args]


# ── a task ───────────────────────────────────────────────────────────────────────────────────────


def _claude(
    prompt: str,
    cwd: Path,
    budget: float,
    log: Path,
    judge: bool = False,
    container: Container | None = None,
) -> dict:
    """One headless Claude Code call; its JSON result, or an error entry."""
    args = [
        "-p",
        prompt,
        "--output-format",
        "json",
        "--max-budget-usd",
        f"{budget:.2f}",
    ]
    args += JUDGE_ARGS if judge else WORKER_ARGS
    name = f"{container.name}-{'judge' if judge else 'worker'}" if container else ""
    if container:
        argv, env = container_command(name, cwd, container, args), None
    else:
        argv, env = ["claude", *args], filtered_env()
    try:
        proc = subprocess.run(
            argv,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=RUN_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        if container:
            _docker("kill", name)  # the client dies with the timeout; its container would not
        log.write_text(f"stopped after {RUN_TIMEOUT_S} s\n", encoding="utf-8")
        return {
            "is_error": True,
            "subtype": "timeout",
            "result": f"no end after {RUN_TIMEOUT_S} s",
        }
    log.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"is_error": True, "result": f"no JSON result (exit {proc.returncode})"}
    return result if isinstance(result, dict) else {"is_error": True, "result": "unexpected result"}


def parse_verdict(text: str) -> dict:
    """The judge's JSON line, or a reject that says why it could not be read."""
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    try:
        verdict = json.loads(match.group(0)) if match else {}
    except ValueError:
        verdict = {}
    if verdict.get("verdict") not in ("approve", "reject"):
        return {
            "verdict": "reject",
            "reasons": ["the judge's answer could not be read"],
        }
    return {
        "verdict": verdict["verdict"],
        "reasons": list(verdict.get("reasons") or []),
    }


def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )


def run(task_id: str = "") -> dict:
    queued = [t for t in all_tasks() if t["status"] == "queued"]
    task = load(task_id) if task_id else (queued[0] if queued else None)
    if task is None:
        raise KeyError("no queued task")
    if task.get("isolation", "container") == "container":
        problem = container_problem()
        if problem:
            raise ValueError(problem)  # the task stays queued: nothing ran
        if not image_present():
            print(f"pak task: building {image_tag()}, once per version", file=sys.stderr)
            build_image()
    folder = tasks_dir() / task["id"]
    workspace = folder / "workspace"
    task.update(status="running", started=_now())
    _save(task)

    if workspace.exists():
        shutil.move(str(workspace), str(folder / f"workspace-{_now()}"))  # a retry starts clean
    cloned = subprocess.run(
        [
            "git",
            "clone",
            "--quiet",
            "--local",
            "--no-hardlinks",
            task["repo"],
            str(workspace),
        ],
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT_S,
        check=False,
    )
    if cloned.returncode != 0:
        return _save({**task, "status": "failed", "error": cloned.stderr.strip()[:500]})

    with _isolated(task, folder) as container:
        task = _work(task, folder, workspace, container)
    if container:
        task["egress"] = egress.summary(folder / "egress.jsonl")
    return _save({**task, "finished": _now()})


def _work(task: dict, folder: Path, workspace: Path, container: Container | None) -> dict:
    """The engine's turn, the patch and its review: the task with its new status."""
    work_budget = task["budget_usd"] * (1 - JUDGE_SHARE)
    prompt = WORKER_PROMPT.format(task=task["prompt"])
    worker = _claude(prompt, workspace, work_budget, folder / "worker.log", container=container)
    task["worker"] = {
        "cost_usd": worker.get("total_cost_usd"),
        "stopped": worker.get("subtype"),
        "error": bool(worker.get("is_error")),
    }
    if worker.get("is_error") or worker.get("subtype") not in (None, "success"):
        return {**task, "status": "stopped"}

    _git("add", "-A", cwd=workspace)
    patch = _git("diff", "--cached", "--binary", cwd=workspace).stdout
    if not patch.strip():
        return {**task, "status": "no_change"}
    (folder / "patch.diff").write_text(patch, encoding="utf-8")

    empty = folder / "judge"  # the review sees the patch in its prompt and nothing on disk
    empty.mkdir(exist_ok=True)
    judge = _claude(
        JUDGE_PROMPT.format(task=task["prompt"], patch=patch[:MAX_PATCH_CHARS]),
        empty,
        task["budget_usd"] * JUDGE_SHARE,
        folder / "judge.log",
        judge=True,
        container=container,
    )
    verdict = parse_verdict(str(judge.get("result", "")))
    (folder / "verdict.json").write_text(json.dumps(verdict, indent=2) + "\n", encoding="utf-8")
    status = "approved" if verdict["verdict"] == "approve" else "rejected"
    return {**task, "status": status, "patch": str(folder / "patch.diff")}


def describe(task: dict) -> str:
    isolation = task.get("isolation", "container")
    line = f"{task['id']}  {task['status']:9}  {isolation:9}  {task['prompt'][:60]}"
    if task.get("patch"):
        line += f"\n            patch: {task['patch']}"
    denied = (task.get("egress") or {}).get("denied")
    if denied:
        line += f"\n            refused: {', '.join(denied)}"
    return line


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="a task to a reviewed patch, never to a commit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_add = sub.add_parser("add", help="queue a task")
    p_add.add_argument("prompt")
    p_add.add_argument("--repo", default=".")
    p_add.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD, help="USD for the task")
    p_add.add_argument(
        "--isolation",
        choices=ISOLATIONS,
        default="container",
        help="host runs the engine on this machine, with the guards as the only line",
    )
    p_run = sub.add_parser("run", help="run the oldest queued task, or this one")
    p_run.add_argument("id", nargs="?", default="")
    p_status = sub.add_parser("status", help="one task, or all of them")
    p_status.add_argument("id", nargs="?", default="")
    sub.add_parser("image", help="build the container image")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "add":
            task = add(args.prompt, args.repo, args.budget, args.isolation)
            print(f"queued {task['id']}: {task['prompt'][:80]}")
            return 0
        if args.cmd == "run":
            task = run(args.id)
            print(describe(task))
            return 0 if task["status"] in ("approved", "no_change") else 1
        if args.cmd == "image":
            print(build_image())
            return 0
        tasks = [load(args.id)] if args.id else all_tasks()
    except (KeyError, ValueError) as e:
        print(f"pak task: {e.args[0]}", file=sys.stderr)
        return 2
    for task in tasks:
        print(describe(task))
    if not tasks:
        print("no tasks yet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
