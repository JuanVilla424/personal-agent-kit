"""bin/pak_worker.py with a stand-in `claude` and `docker` on PATH and real git: a task never lands
as a commit, and in its container it sees only what it is given.

bin/tests/guard-e2e/worker.sh runs the same flow with the real Claude Code, the real container
and a scripted model.
"""

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))

import pak_worker as w  # noqa: E402

FAKE_CLAUDE = """#!/usr/bin/env python3
import json, os, sys
prompt = sys.argv[sys.argv.index("-p") + 1]
mode = os.environ.get("FAKE_MODE", "approve")
if prompt.startswith("You review"):
    verdict = "reject" if mode == "reject" else "approve"
    text = json.dumps({"verdict": verdict, "reasons": ["checked"]})
    print(json.dumps({"subtype": "success", "result": text, "total_cost_usd": 0.01}))
elif mode == "budget":
    print(json.dumps({"subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 9.0}))
elif mode == "garbage":
    print("not json")
else:
    if mode != "nochange":
        open("hello.txt", "w").write("hello\\n")
    print(json.dumps({"subtype": "success", "result": "done", "total_cost_usd": 0.02}))
"""
# Docker as the worker uses it: `run` starts the engine after "--" in the folder mounted at /work,
# and can knock on the egress socket first, or hang.
FAKE_DOCKER = """#!/usr/bin/env python3
import json, os, socket, subprocess, sys, time
args = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a") as log:
    log.write(json.dumps(args) + "\\n")
if args[0] == "info":
    sys.exit(1 if os.environ.get("FAKE_DOCKER_DOWN") else 0)
if args[:2] == ["image", "inspect"]:
    sys.exit(1 if os.environ.get("FAKE_NO_IMAGE") else 0)
if args[0] != "run":
    sys.exit(0)
mounts = {}
for flag, value in zip(args, args[1:]):
    if flag == "--mount":
        fields = dict(f.split("=", 1) for f in value.split(",") if "=" in f)
        mounts[fields["target"]] = fields["source"]
if os.environ.get("FAKE_EGRESS"):
    with socket.socket(socket.AF_UNIX) as s:
        s.connect(mounts["/run/pak"] + "/egress.sock")
        s.sendall(("CONNECT " + os.environ["FAKE_EGRESS"] + " HTTP/1.1\\r\\n\\r\\n").encode())
        s.recv(64)
if os.environ.get("FAKE_HANG"):
    time.sleep(30)
engine = args[args.index("--") + 1:]
sys.exit(subprocess.run(engine, cwd=mounts["/work"]).returncode)
"""


@pytest.fixture(params=["container", "host"])
def isolation(request):
    return request.param


@pytest.fixture
def env(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in (("claude", FAKE_CLAUDE), ("docker", FAKE_DOCKER)):
        (bin_dir / name).write_text(script, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("PAK_TASKS_DIR", str(tmp_path / "tasks"))
    monkeypatch.setenv("FAKE_DOCKER_LOG", str(tmp_path / "docker.jsonl"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    for key in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_BASE_URL", "PAK_WORKER_EGRESS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(w, "ENV_ALLOWLIST", w.ENV_ALLOWLIST + ("FAKE_MODE",))
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@localhost"]
    subprocess.run(["git", "init", "-q", "-b", "dev", str(repo)], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "demo"], check=True)
    return repo


def _commits(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def docker_calls(kind: str = "run") -> list[list[str]]:
    log = Path(os.environ["FAKE_DOCKER_LOG"])
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return [args for args in map(json.loads, lines) if args[0] == kind]


def mounts_of(args: list[str]) -> dict[str, str]:
    """target -> "source" or "source (read-only)", from a docker run's --mount flags."""
    found = {}
    for flag, value in zip(args, args[1:]):
        if flag == "--mount":
            fields = value.split(",")
            pairs = dict(f.split("=", 1) for f in fields if "=" in f)
            read_only = " (read-only)" if "readonly" in fields else ""
            found[pairs["target"]] = pairs["source"] + read_only
    return found


def test_an_approved_task_leaves_a_patch_and_never_a_commit(env, monkeypatch, isolation):
    monkeypatch.setenv("FAKE_MODE", "approve")
    task = w.add("create hello.txt", str(env), budget=1.0, isolation=isolation)
    done = w.run()
    assert done["status"] == "approved" and done["id"] == task["id"]
    patch = Path(done["patch"]).read_text(encoding="utf-8")
    assert "+++ b/hello.txt" in patch
    assert not (env / "hello.txt").exists() and _commits(env) == "1"
    assert done["worker"] == {"cost_usd": 0.02, "stopped": "success", "error": False}
    assert done["isolation"] == isolation


@pytest.mark.parametrize(
    "mode, status",
    [
        ("reject", "rejected"),
        ("budget", "stopped"),
        ("garbage", "stopped"),
        ("nochange", "no_change"),
    ],
)
def test_every_other_ending_is_recorded(env, monkeypatch, isolation, mode, status):
    monkeypatch.setenv("FAKE_MODE", mode)
    task = w.add("create hello.txt", str(env), isolation=isolation)
    assert w.run(task["id"])["status"] == status
    assert w.load(task["id"])["status"] == status


def test_a_retry_keeps_the_previous_workspace(env, monkeypatch, isolation):
    monkeypatch.setenv("FAKE_MODE", "approve")
    task = w.add("create hello.txt", str(env), isolation=isolation)
    w.run(task["id"])
    w.run(task["id"])
    folder = Path(os.environ["PAK_TASKS_DIR"]) / task["id"]
    assert len(list(folder.glob("workspace-*"))) == 1


def test_a_clone_that_fails_is_a_failed_task(env, monkeypatch, tmp_path, isolation):
    task = w.add("x", str(env), isolation=isolation)
    stored = w.load(task["id"])
    stored["repo"] = str(tmp_path / "gone")
    w._save(stored)
    assert w.run(task["id"])["status"] == "failed"


def test_a_task_that_runs_too_long_is_stopped_and_its_container_killed(env, monkeypatch):
    monkeypatch.setenv("FAKE_HANG", "1")
    monkeypatch.setattr(w, "RUN_TIMEOUT_S", 1)
    task = w.add("create hello.txt", str(env))
    done = w.run(task["id"])
    assert done["status"] == "stopped" and done["worker"]["stopped"] == "timeout"
    assert docker_calls("kill") == [["kill", f"pak-task-{task['id']}-worker"]]


@pytest.mark.parametrize(
    "prompt, repo_name, budget, isolation, message",
    [
        ("", "repo", 1.0, "container", "prompt"),
        ("x", "not-a-repo", 1.0, "container", "not a git"),
        ("x", "repo", 0, "container", "positive"),
        ("x", "repo", 1.0, "vm", "container or host"),
    ],
)
def test_a_bad_task_is_refused(env, tmp_path, prompt, repo_name, budget, isolation, message):
    (tmp_path / "not-a-repo").mkdir()
    with pytest.raises(ValueError, match=message):
        w.add(prompt, str(tmp_path / repo_name), budget, isolation)


def test_only_the_allowlist_reaches_the_engine_on_the_host():
    env = w.filtered_env(
        {
            "PATH": "/bin",
            "HOME": "/h",
            "AWS_SECRET_ACCESS_KEY": "s",
            "GITHUB_TOKEN": "t",
        }
    )
    assert env == {"PATH": "/bin", "HOME": "/h"}


def test_the_container_has_no_network_and_sees_only_what_it_is_given(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "approve")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "never-inside")
    task = w.add("create hello.txt", str(env))
    w.run(task["id"])
    worker, judge = docker_calls()
    folder = Path(os.environ["PAK_TASKS_DIR"]) / task["id"]
    for args in (worker, judge):
        line = " ".join(args)
        for flag in (
            "--network none",
            "--read-only",
            "--cap-drop ALL",
            "--init",
            "--rm",
        ):
            assert flag in line
        assert "--security-opt no-new-privileges" in line
        assert f"--user {os.getuid()}:{os.getgid()}" in line
        assert "test-not-a-key" not in line and "never-inside" not in line
        assert args[args.index("ANTHROPIC_API_KEY") - 1] == "--env"  # by name, never by value
        mounts = mounts_of(args)
        assert mounts[w.HOME] == str(folder / "home")
        assert re.match(r"/\S+/pak-egress-\w+$", mounts["/run/pak"])
        kit = {target: source for target, source in mounts.items() if target.startswith("/pak")}
        assert kit == {f"/pak/{part}": f"{w.REPO_ROOT / part} (read-only)" for part in w.KIT_PARTS}
        assert str(w.REPO_ROOT) not in mounts.values()
        assert not any(".claude" in source for source in mounts.values())
        assert w.image_tag() in args and args[args.index("--") + 1] == "claude"
    assert mounts_of(worker)["/work"] == str(folder / "workspace")
    assert "bypassPermissions" in worker
    assert mounts_of(judge)["/work"] == str(folder / "judge")
    assert "bypassPermissions" not in judge and judge[judge.index("--tools") + 1] == ""
    assert worker[worker.index("--name") + 1] == f"pak-task-{task['id']}-worker"


def test_the_container_home_holds_only_the_guard_hooks(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "approve")
    task = w.add("create hello.txt", str(env))
    w.run(task["id"])
    home = Path(os.environ["PAK_TASKS_DIR"]) / task["id"] / "home"
    settings = json.loads((home / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert list(settings) == ["hooks"] and list(settings["hooks"]) == ["PreToolUse"]
    commands = {h["command"] for group in settings["hooks"]["PreToolUse"] for h in group["hooks"]}
    assert commands == {
        "/pak/local/hooks/pre-write-guard.sh",
        "/pak/local/hooks/rm-guard.sh",
        "/pak/local/hooks/auto-guard.py",
        "/pak/local/hooks/url-guard.py",
    }


def test_a_refused_connection_is_recorded_with_the_task(env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE", "approve")
    monkeypatch.setenv("FAKE_EGRESS", "example.com:443")
    task = w.add("create hello.txt", str(env))
    assert w.main(["run", task["id"]]) == 0
    assert w.load(task["id"])["egress"] == {"allowed": 0, "denied": ["example.com:443"]}
    assert "refused: example.com:443" in capsys.readouterr().out


def test_a_model_on_the_loopback_is_forwarded_into_the_container(env, monkeypatch):
    monkeypatch.setenv("FAKE_MODE", "approve")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:8123")
    w.run(w.add("create hello.txt", str(env))["id"])
    worker = docker_calls()[0]
    assert worker[worker.index("--forward") + 1] == "127.0.0.1:8123"
    assert "ANTHROPIC_BASE_URL=http://127.0.0.1:8123" in worker


@pytest.mark.parametrize(
    "setup, message",
    [
        ("no_docker", "--isolation host"),
        ("docker_down", "does not answer"),
        ("no_key", "CLAUDE_CODE_OAUTH_TOKEN"),
        ("bad_egress", "PAK_WORKER_EGRESS"),
    ],
)
def test_without_docker_or_a_key_the_task_is_refused_and_stays_queued(
    env, monkeypatch, setup, message
):
    if setup == "no_docker":
        monkeypatch.setattr(w.shutil, "which", lambda name: None)
    elif setup == "docker_down":
        monkeypatch.setenv("FAKE_DOCKER_DOWN", "1")
    elif setup == "no_key":
        monkeypatch.delenv("ANTHROPIC_API_KEY")
    else:
        monkeypatch.setenv("PAK_WORKER_EGRESS", "pypi.org")
    task = w.add("create hello.txt", str(env))
    with pytest.raises(ValueError, match=re.escape(message)):
        w.run(task["id"])
    assert w.load(task["id"])["status"] == "queued"
    assert docker_calls() == []


def test_a_missing_image_is_built_first(env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE", "approve")
    monkeypatch.setenv("FAKE_NO_IMAGE", "1")
    w.run(w.add("create hello.txt", str(env))["id"])
    (build,) = docker_calls("build")
    assert build[build.index("--tag") + 1] == w.image_tag()
    assert f"CLAUDE_CODE_VERSION={w.claude_code_version()}" in build
    assert w.main(["image"]) == 0 and capsys.readouterr().out.strip() == w.image_tag()


def test_the_image_is_pinned_to_a_version_and_its_dockerfile(tmp_path, monkeypatch):
    version = (w.REPO_ROOT / "configs" / "claude-code.version").read_text().strip()
    digest = hashlib.sha256(w.DOCKERFILE.read_bytes()).hexdigest()[:8]
    assert w.image_tag() == f"pak-worker:{version}-{digest}"
    assert re.search(r"^FROM \S+:\S+@sha256:[0-9a-f]{64}$", w.DOCKERFILE.read_text(), re.M)
    unpinned = tmp_path / "claude-code.version"
    unpinned.write_text("latest\n", encoding="utf-8")
    monkeypatch.setattr(w, "CLAUDE_CODE_VERSION", unpinned)
    with pytest.raises(ValueError, match="one exact version"):
        w.image_tag()


def test_a_failed_build_says_so(env, monkeypatch, tmp_path):
    failing = tmp_path / "bin" / "docker"
    failing.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="failed"):
        w.build_image()
    monkeypatch.setattr(w, "BUILD_TIMEOUT_S", 0.01)
    failing.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    with pytest.raises(ValueError, match="did not end"):
        w.build_image()


def test_an_unreadable_verdict_is_a_reject():
    assert w.parse_verdict('ok {"verdict": "approve", "reasons": ["fine"]}') == {
        "verdict": "approve",
        "reasons": ["fine"],
    }
    assert w.parse_verdict("no json here")["verdict"] == "reject"
    assert w.parse_verdict('{"verdict": "maybe"}')["verdict"] == "reject"
    assert w.parse_verdict("{broken")["verdict"] == "reject"


def test_the_cli_adds_runs_and_lists(env, monkeypatch, capsys):
    monkeypatch.setenv("FAKE_MODE", "approve")
    assert w.main(["status"]) == 0 and "no tasks yet" in capsys.readouterr().out
    assert w.main(["add", "create hello.txt", "--repo", str(env)]) == 0
    task_id = capsys.readouterr().out.split()[1].rstrip(":")
    assert w.main(["run"]) == 0
    assert "approved" in capsys.readouterr().out
    assert w.main(["status", task_id]) == 0 and "patch:" in capsys.readouterr().out
    assert w.main(["run"]) == 2  # nothing queued
    assert w.main(["status", "nope"]) == 2
    assert w.main(["add", "", "--repo", str(env)]) == 2
    monkeypatch.setenv("FAKE_MODE", "reject")
    w.main(["add", "again", "--repo", str(env), "--isolation", "host"])
    assert w.main(["run"]) == 1
    assert "host" in capsys.readouterr().out
    assert (
        json.loads((Path(os.environ["PAK_TASKS_DIR"]) / task_id / "verdict.json").read_text())[
            "verdict"
        ]
        == "approve"
    )


def test_doctor_reports_the_worker(env, monkeypatch):
    import pak_cli

    tag = w.image_tag()
    assert pak_cli.check_worker() == (
        "ok",
        f"tasks run in {tag}, with no network but the model API",
    )
    monkeypatch.setenv("FAKE_NO_IMAGE", "1")
    assert pak_cli.check_worker() == ("warn", f"{tag} is not built yet: pak task image")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    state, detail = pak_cli.check_worker()
    assert (
        state == "warn" and "CLAUDE_CODE_OAUTH_TOKEN" in detail and "test-not-a-key" not in detail
    )
    monkeypatch.setattr(pak_cli.shutil, "which", lambda name: None)
    assert pak_cli.check_worker()[0] == "off"
