"""Coverage for local/hooks/rm-guard.sh — invoked as a real subprocess with the
same JSON-on-stdin contract Claude Code uses, matching how the hook is actually run.
"""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "rm-guard.sh"


def _run(command: str):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        ["bash", str(SCRIPT)], input=payload, capture_output=True, text=True, timeout=10
    )


def test_blocks_rm_rf_venv():
    result = _run("rm -rf .venv")
    assert result.returncode == 2
    assert "BLOCKED" in result.stderr


def test_blocks_rm_rf_git():
    result = _run("rm -rf .git")
    assert result.returncode == 2


def test_blocks_rm_rf_node_modules_subpath():
    result = _run("rm -rf node_modules/some-pkg")
    assert result.returncode == 2


def test_blocks_flags_in_reverse_order():
    result = _run("rm -fr .venv")
    assert result.returncode == 2


def test_blocks_separate_flags():
    result = _run("rm -r -f dist")
    assert result.returncode == 2


def test_allows_rm_rf_on_non_sensitive_path():
    result = _run("rm -rf /home/user/some_output_dir")
    assert result.returncode == 0


def test_allows_force_only_without_recursive():
    result = _run("rm -f notes.txt")
    assert result.returncode == 0


def test_allows_recursive_only_without_force():
    result = _run("rm -r some_dir")
    assert result.returncode == 0


def test_allows_reading_inside_venv():
    result = _run("cat .venv/bin/activate")
    assert result.returncode == 0


def test_allows_missing_command():
    payload = json.dumps({"tool_name": "Bash", "tool_input": {}})
    result = subprocess.run(
        ["bash", str(SCRIPT)], input=payload, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
