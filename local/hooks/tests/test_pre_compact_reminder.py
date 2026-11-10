"""Coverage for local/hooks/pre-compact-reminder.sh — stateless, always emits the
same PreCompact reminder regardless of stdin.
"""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "pre-compact-reminder.sh"


def _run():
    return subprocess.run(
        ["bash", str(SCRIPT)], input="{}", capture_output=True, text=True, timeout=10
    )


def test_exits_zero():
    assert _run().returncode == 0


def test_emits_pre_compact_reminder_pointing_at_the_skill():
    out = json.loads(_run().stdout)
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreCompact"
    assert "pre-compact" in spec["additionalContext"]
    assert "temp/current-context.md" in spec["additionalContext"]
