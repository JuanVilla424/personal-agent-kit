"""Coverage for local/hooks/pre-write-guard.sh — invoked as a real subprocess with
the same JSON-on-stdin contract Claude Code uses.

The fake AWS key below is built by concatenation on purpose: a literal contiguous
AKIA... string in this file would itself trip this repo's own pre-write-guard hook
when this test file is written/edited (confirmed the hard way while authoring it).
"""

import json
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "pre-write-guard.sh"
FAKE_AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def _run(tool_name: str, file_path: str, **extra_input):
    payload = json.dumps(
        {"tool_name": tool_name, "tool_input": {"file_path": file_path, **extra_input}}
    )
    return subprocess.run(
        ["bash", str(SCRIPT)], input=payload, capture_output=True, text=True, timeout=10
    )


def test_blocks_writing_dotenv():
    result = _run("Write", "/repo/.env", content="SECRET=1")
    assert result.returncode == 2
    assert "BLOCKED" in result.stderr


def test_allows_dotenv_template():
    result = _run("Write", "/repo/.env.template", content="SECRET=<placeholder>")
    assert result.returncode == 0


def test_blocks_pem_file():
    result = _run("Write", "/repo/certs/server.pem", content="anything at all")
    assert result.returncode == 2


def test_blocks_versioned_filename():
    result = _run("Write", "/repo/scripts/deploy-v2.sh", content="#!/usr/bin/env bash\ntrue\n")
    assert result.returncode == 2
    assert "versioned" in result.stderr


def test_allows_normal_filename():
    result = _run("Write", "/repo/scripts/deploy.sh", content="#!/usr/bin/env bash\ntrue\n")
    assert result.returncode == 0


def test_blocks_hardcoded_aws_key():
    result = _run("Write", "/repo/config.py", content=f"KEY = '{FAKE_AWS_KEY}'")
    assert result.returncode == 2
    assert "hardcoded secret" in result.stderr


def test_allows_clean_python_content():
    result = _run("Write", "/repo/config.py", content="import os\nX = os.getenv('X')\n")
    assert result.returncode == 0


def test_blocks_invalid_python_syntax_on_write():
    result = _run("Write", "/repo/broken.py", content="def f(:\n    pass\n")
    assert result.returncode == 2
    assert "syntax" in result.stderr


def test_edit_checks_new_string_for_secrets():
    result = _run(
        "Edit",
        "/repo/config.py",
        old_string="X = 1",
        new_string=f"KEY = '{FAKE_AWS_KEY}'",
    )
    assert result.returncode == 2


def test_allows_missing_file_path():
    payload = json.dumps({"tool_name": "Write", "tool_input": {"content": "x"}})
    result = subprocess.run(
        ["bash", str(SCRIPT)], input=payload, capture_output=True, text=True, timeout=10
    )
    assert result.returncode == 0
