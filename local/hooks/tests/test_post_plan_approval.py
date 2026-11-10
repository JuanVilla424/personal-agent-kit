"""Coverage for local/hooks/post-plan-approval.sh.

Only the safe early-exit path is tested here: `TASKS_FILE` is computed relative to
the script's own location (BASH_SOURCE), not to $HOME, so there is no environment
seam to redirect the append target without touching this repo's real TASKS.md. With
an isolated $HOME that has no ~/.claude/plans/, the script finds no plan and exits
before ever reaching the append — real script, real behavior, zero side effects.
Covering the append path itself would need a small testability seam added to the
script (e.g. a TASKS_FILE override) — flagged, not done here to keep this change
minimal.
"""

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "post-plan-approval.sh"


def test_exits_zero_when_no_plans_directory_exists(tmp_path):
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input="{}",
        capture_output=True,
        text=True,
        timeout=10,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert result.stdout == ""


def test_exits_zero_when_plans_directory_is_empty(tmp_path):
    (tmp_path / ".claude" / "plans").mkdir(parents=True)
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        input="{}",
        capture_output=True,
        text=True,
        timeout=10,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert result.stdout == ""
