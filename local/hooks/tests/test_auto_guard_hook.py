"""local/hooks/auto-guard.py — every exit of the Claude Code hook.

The corpus runs through the real hook as a subprocess (bin/tests/test_guard_corpus.py); this file
reaches the branches a corpus case never takes: a nested run, a payload that is not a tool call,
auto-approval, and a guard that cannot judge.
"""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HOOKS.parents[1] / "bin"))
import auto_guard  # noqa: E402

BLOCKED = "git push --force origin dev"  # force_push → block
CHALLENGED = "git push origin --delete feature-x"  # delete_shared → challenge


@pytest.fixture
def hook(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location(
        "auto_guard_hook_under_test", str(HOOKS / "auto-guard.py")
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.delenv("PAK_HOOK_RUNNING", raising=False)
    monkeypatch.setattr(auto_guard, "GUARD_LOG", tmp_path / "guard.jsonl")
    monkeypatch.setattr(auto_guard, "auto_approve_enabled", lambda: False)
    return mod


def _run(hook, monkeypatch, capsys, payload):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    monkeypatch.setattr(sys, "stdin", io.StringIO(data))
    with pytest.raises(SystemExit) as exc:
        hook.main()
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def _bash(command):
    return {"tool_name": "Bash", "tool_input": {"command": command}}


def test_nothing_to_judge_passes(hook, monkeypatch, capsys):
    monkeypatch.setenv("PAK_HOOK_RUNNING", "1")
    assert _run(hook, monkeypatch, capsys, _bash(BLOCKED))[0] == 0  # never recurse into the judge
    monkeypatch.delenv("PAK_HOOK_RUNNING")
    assert _run(hook, monkeypatch, capsys, "{not json")[0] == 0
    assert _run(hook, monkeypatch, capsys, {"tool_name": "Read", "tool_input": {}})[0] == 0
    assert _run(hook, monkeypatch, capsys, _bash("ls -la"))[0] == 0


def test_a_block_is_exit_2_and_logged(hook, monkeypatch, capsys, tmp_path):
    code, _out, err = _run(hook, monkeypatch, capsys, _bash(BLOCKED))
    assert code == 2 and "BLOCKED" in err and "[force_push]" in err
    entry = json.loads((tmp_path / "guard.jsonl").read_text().splitlines()[-1])
    assert (entry["engine"], entry["rule"]) == ("claude", "force_push")


def test_a_challenge_asks_the_human_unless_auto_approval_is_on(hook, monkeypatch, capsys):
    code, out, _err = _run(hook, monkeypatch, capsys, _bash(CHALLENGED))
    decision = json.loads(out)["hookSpecificOutput"]
    assert code == 0 and decision["permissionDecision"] == "ask"
    assert "[delete_shared]" in decision["permissionDecisionReason"]

    approved = []
    monkeypatch.setattr(auto_guard, "auto_approve_enabled", lambda: True)
    monkeypatch.setattr(
        auto_guard, "auto_approve_result", lambda hit, cmd, eng: approved.append(hit.rule_id)
    )
    code, out, _err = _run(hook, monkeypatch, capsys, _bash(CHALLENGED))
    assert (code, out, approved) == (0, "", ["delete_shared"])


def test_a_guard_that_cannot_judge_blocks(hook, monkeypatch, capsys):
    def broken(_command):
        raise RuntimeError("rules unreadable")

    monkeypatch.setattr(auto_guard, "check_block_rules", broken)
    code, _out, err = _run(hook, monkeypatch, capsys, _bash("ls -la"))
    assert code == 2 and "could not judge" in err and "RuntimeError" in err
