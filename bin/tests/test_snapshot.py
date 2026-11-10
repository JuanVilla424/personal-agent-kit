"""bin/snapshot.py: copies of a work tree, outside it, that bring back what a script destroyed."""

import fcntl
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "bin"))

import snapshot  # noqa: E402

GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@t"]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *GIT_ID, *args], capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setenv("PAK_SNAPSHOTS_DIR", str(tmp_path / "store"))
    repo = tmp_path / "app"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "dev")
    (repo / "a.txt").write_text("one\n")
    (repo / ".gitignore").write_text("*.log\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "init")
    (repo / "debug.log").write_text("noise\n")
    (repo / "draft.md").write_text("not committed yet\n")
    return repo


def project_state(repo: Path) -> tuple[str, str, int]:
    """What a snapshot must never change in the project's own repository."""
    index = repo / ".git" / "index"
    return git(repo, "for-each-ref"), git(repo, "count-objects", "-v"), index.stat().st_mtime_ns


def test_a_snapshot_holds_the_work_tree_and_skips_what_git_ignores(project):
    before = project_state(project)
    assert snapshot.take(project, "test")[0] == 0
    ((snapshot_id, _, reason),) = snapshot.history(project)
    files = git(
        project,
        f"--git-dir={snapshot.store_for(project)}",
        "ls-tree",
        "-r",
        "--name-only",
        snapshot_id,
    ).split()
    assert (reason, sorted(files)) == ("test", [".gitignore", "a.txt", "draft.md"])
    assert project_state(project) == before


def test_an_unchanged_tree_is_not_taken_again(project):
    snapshot.take(project)
    assert snapshot.take(project)[1].startswith("unchanged since")
    (project / "a.txt").write_text("two\n")
    snapshot.take(project, "second")
    assert [r for _, _, r in snapshot.history(project)] == ["second", "manual"]


def test_restore_brings_back_what_a_script_deleted(project):
    snapshot.take(project, "session-start")
    first = snapshot.history(project)[0][0]
    (project / "draft.md").unlink()
    (project / "a.txt").write_text("broken\n")
    (project / "extra.txt").write_text("made after\n")
    code, _ = snapshot.restore(project, first, [])
    assert code == 0
    assert (project / "draft.md").read_text() == "not committed yet\n"
    assert (project / "a.txt").read_text() == "one\n"
    assert (project / "extra.txt").exists()  # restore deletes nothing
    assert snapshot.history(project)[0][2] == f"before restoring {first[:12]}"


def test_a_large_file_is_left_out(project, monkeypatch):
    monkeypatch.setenv("PAK_SNAPSHOT_MAX_FILE_MB", "0.001")
    (project / "big.bin").write_bytes(b"x" * 4096)
    code, message = snapshot.take(project)
    files = git(
        project,
        f"--git-dir={snapshot.store_for(project)}",
        "ls-tree",
        "-r",
        "--name-only",
        snapshot.history(project)[0][0],
    ).split()
    assert code == 0 and "1 large file(s) left out" in message and "big.bin" not in files


def test_the_store_is_private(project):
    snapshot.take(project)
    assert snapshot.root().stat().st_mode & 0o777 == 0o700


def test_outside_a_work_tree_nothing_is_taken(tmp_path, monkeypatch):
    monkeypatch.setenv("PAK_SNAPSHOTS_DIR", str(tmp_path / "store"))
    assert snapshot.take(tmp_path)[0] == 1


def test_a_running_snapshot_is_not_doubled(project):
    snapshot.take(project)
    with open(snapshot.store_for(project) / "pak-snapshot.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert snapshot.take(project)[0] == 1


def test_the_command_line(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    assert snapshot.main(["take", "--reason", "cli"]) == 0
    first = snapshot.history(project)[0][0]
    assert snapshot.main(["list"]) == 0 and "cli" in capsys.readouterr().out
    assert snapshot.main(["show", first, "a.txt"]) == 0 and capsys.readouterr().out == "one\n"
    (project / "a.txt").write_text("two\n")
    assert snapshot.main(["diff", first]) == 0 and "a.txt" in capsys.readouterr().out
    assert snapshot.main(["show", "no-such-snapshot"]) == 2
    assert snapshot.main(["restore", first, "a.txt"]) == 0
    assert (project / "a.txt").read_text() == "one\n"


def test_a_challenge_in_claude_code_snapshots_the_session_first(project, tmp_path):
    """The real hook, as Claude Code runs it: a challenge answers at once and copies the
    session's repository in the background."""
    import json
    import os
    import time

    env = {
        **os.environ,
        "AUTO_GUARD_LOG": str(tmp_path / "log.jsonl"),
        "AUTO_GUARD_APPROVALS": str(tmp_path / "approvals.json"),
    }
    env.pop("PAK_HOOK_RUNNING", None)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "chmod 777 draft.md"},
        "cwd": str(project),
    }
    proc = subprocess.run(
        [sys.executable, str(REPO / "local" / "hooks" / "auto-guard.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"] == "ask"
    deadline = time.monotonic() + 20
    while not snapshot.history(project) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert snapshot.history(project)[0][2] == "challenge:open_permissions"


def test_doctor_reports_the_snapshots(project, monkeypatch):
    import pak_cli

    assert pak_cli.check_snapshots()[0] == "off"
    snapshot.take(project)
    state, detail = pak_cli.check_snapshots()
    assert state == "ok" and detail.startswith("1 project(s)")
    monkeypatch.setattr(pak_cli, "SNAPSHOT_WARN_BYTES", 0)
    assert pak_cli.check_snapshots()[0] == "warn"
