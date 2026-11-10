"""Coverage for local/hooks/token-check-reminder.sh — stateless, always emits the
same UserPromptSubmit reminder regardless of stdin.
"""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "token-check-reminder.sh"


def _run():
    return subprocess.run(
        ["bash", str(SCRIPT)], input="{}", capture_output=True, text=True, timeout=10
    )


def test_exits_zero():
    assert _run().returncode == 0


def test_emits_user_prompt_submit_reminder():
    out = json.loads(_run().stdout)
    spec = out["hookSpecificOutput"]
    assert spec["hookEventName"] == "UserPromptSubmit"
    assert "protocols/token-management.md" in spec["additionalContext"]


def test_ignores_stdin_content():
    result = subprocess.run(
        ["bash", str(SCRIPT)], input="not even json", capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
