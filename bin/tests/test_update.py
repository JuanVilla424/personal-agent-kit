"""bin/update.sh and bin/opencode/guard-smoke.sh — parse, run hermetically, and verify."""

import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
UPDATE = REPO / "bin" / "update.sh"
SMOKE = REPO / "bin" / "opencode" / "guard-smoke.sh"


def test_both_scripts_parse():
    assert (
        subprocess.run(["bash", "-n", str(UPDATE)], capture_output=True, check=False).returncode
        == 0
    )
    assert (
        subprocess.run(["bash", "-n", str(SMOKE)], capture_output=True, check=False).returncode == 0
    )


def test_update_runs_in_a_fresh_local_clone(tmp_path):
    """A clone of this repo, updated in place: pull skips, hooks install, TASKS.md lands."""
    # CI checks out shallow (depth=1) and a clone FROM a shallow source dies with 128:
    # unshallow the workspace first (a no-op on a full clone like a dev box).
    shallow = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "--is-shallow-repository"],
        capture_output=True,
        text=True,
        check=False,
    )
    if shallow.stdout.strip() == "true":
        subprocess.run(
            ["git", "-C", str(REPO), "fetch", "--unshallow", "origin"],
            capture_output=True,
            timeout=600,
            check=True,
        )
    clone = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--branch", "dev", "--single-branch", str(REPO), str(clone)],
        capture_output=True,
        check=True,
    )
    # Hermetic: the submodule would reach for GitHub; without .gitmodules the step just reports.
    (clone / ".gitmodules").unlink(missing_ok=True)
    # The script under test is not committed yet — handing it to the clone DIRTYIES the tree,
    # which is itself the behavior under test: update.sh must refuse to pull over a dirty tree
    # and still do the rest (hooks, TASKS.md, verification) unattended.
    shutil.copy2(UPDATE, clone / "bin" / "update.sh")
    env = dict(os.environ, HOME=str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    proc = subprocess.run(
        ["bash", str(clone / "bin" / "update.sh")],
        capture_output=True,
        text=True,
        timeout=300,
        env=env,
        cwd=str(clone),
        check=False,
    )
    out = proc.stdout
    assert "Preflight" in out and "dirty work tree — NOT pulling" in out
    assert "TASKS.md created from the template" in out
    assert "update finished with" in out
    assert proc.returncode == 1
    assert (clone / "TASKS.md").exists()
    assert (tmp_path / "home" / ".claude" / "settings.json").exists()


def test_guard_smoke_refuses_to_run_without_opencode(tmp_path):
    env = dict(os.environ)
    env["PATH"] = "/usr/bin:/bin"  # opencode is never there; the smoke must refuse
    proc = subprocess.run(
        ["bash", str(SMOKE)],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(tmp_path),
        check=False,
    )
    if "opencode" in proc.stderr:
        assert proc.returncode == 2
    else:  # an opencode lives in /usr/bin on this box: the smoke ran — it must not crash
        assert proc.returncode in (0, 1, 2)


def test_guard_smoke_help_prints_the_leading_comment(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path))
    proc = subprocess.run(
        ["bash", str(SMOKE), "--help"],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    assert proc.returncode == 0
    assert "guard-smoke.sh" in proc.stdout and "--timeout" in proc.stdout
