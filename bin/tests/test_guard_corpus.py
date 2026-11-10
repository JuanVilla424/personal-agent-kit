"""The guard corpus (evals/datasets/guard-corpus.jsonl) through every way a command reaches the rules.

  - the rules themselves (bin/auto_guard.py check_block_rules)
  - Claude Code's hook (local/hooks/auto-guard.py), as a subprocess with the JSON-on-stdin contract
  - the CLI the OpenCode plugin calls (--stdin --stage1-only --json), as a subprocess

The OpenCode plugin itself runs the same corpus in .opencode/plugins/tests/guard-corpus.test.js.
Cases marked `known_evasion` document what the rules cannot see; they pass today, on purpose, and
the day a rule catches one its expectation flips.
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "bin"))

import auto_guard as ag  # noqa: E402

CORPUS_PATH = REPO / "evals" / "datasets" / "guard-corpus.jsonl"
CORPUS = [json.loads(line) for line in CORPUS_PATH.read_text(encoding="utf-8").splitlines()]
HOOK = REPO / "local" / "hooks" / "auto-guard.py"
CLI = REPO / "bin" / "auto_guard.py"
MIN_BLOCK_CASES = 50
MIN_ALLOW_CASES = 50


def _ids(case: dict) -> str:
    return case["id"]


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """The subprocesses write their audit trail and approvals to temp files, never to logs/."""
    monkeypatch.setenv("AUTO_GUARD_LOG", str(tmp_path / "guard.jsonl"))
    monkeypatch.setenv("AUTO_GUARD_APPROVALS", str(tmp_path / "approvals.json"))
    monkeypatch.delenv("PAK_HOOK_RUNNING", raising=False)
    return tmp_path


def test_the_corpus_is_large_enough_and_well_formed():
    counts = Counter(case["expect"] for case in CORPUS)
    assert counts["block"] >= MIN_BLOCK_CASES
    assert counts["allow"] >= MIN_ALLOW_CASES
    assert set(counts) <= {"block", "challenge", "allow"}
    assert len({case["id"] for case in CORPUS}) == len(CORPUS)
    for case in CORPUS:
        assert ("rule" in case) == (case["expect"] != "allow"), case["id"]


def test_every_rule_has_a_case_that_fires_it():
    fired = {case.get("rule") for case in CORPUS}
    assert {rule["id"] for rule in ag.BLOCK_RULES} <= fired


@pytest.mark.parametrize("case", CORPUS, ids=_ids)
def test_the_rules_give_the_expected_verdict(case):
    hit = ag.check_block_rules(case["command"])
    assert (hit.action if hit else "allow") == case["expect"]
    assert (hit.rule_id if hit else None) == case.get("rule")


@pytest.mark.parametrize("case", CORPUS, ids=_ids)
def test_claude_code_hook_gives_the_expected_verdict(case, isolated_env):
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": case["command"]}})
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if case["expect"] == "block":
        assert proc.returncode == 2
        assert f"[{case['rule']}]" in proc.stderr
    elif case["expect"] == "challenge":
        decision = json.loads(proc.stdout)["hookSpecificOutput"]
        assert proc.returncode == 0
        assert decision["permissionDecision"] == "ask"
        assert f"[{case['rule']}]" in decision["permissionDecisionReason"]
    else:
        assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize("case", CORPUS, ids=_ids)
def test_opencode_cli_gives_the_expected_verdict(case, isolated_env):
    proc = subprocess.run(
        [sys.executable, str(CLI), "--stdin", "--stage1-only", "--json", "--engine", "opencode"],
        input=case["command"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    resp = json.loads(proc.stdout)
    if case["expect"] == "allow":
        assert resp == {"allowed": True}
        assert proc.returncode == 0
        return
    assert resp["allowed"] is False
    assert (resp["action"], resp["rule"]) == (case["expect"], case["rule"])
    assert proc.returncode == 1
    if case["expect"] == "challenge":
        assert resp["approve"]["cmd"].startswith(f"python3 {CLI} approve ")
