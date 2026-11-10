"""Coverage for evals/run_evals.py pure logic (no model calls) + dataset validity."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_evals import check_asserts, gate, load_tasks  # noqa: E402


def test_must_include_pass():
    ok, fails = check_asserts(
        "I recommend downsizing to m6", {"asserts": {"must_include": [r"(?i)downsiz"]}}
    )
    assert ok and not fails


def test_must_include_fail():
    ok, fails = check_asserts(
        "shut down the instance", {"asserts": {"must_include": [r"(?i)downsiz"]}}
    )
    assert not ok and any("missing" in f for f in fails)


def test_must_not_include_fail():
    ok, fails = check_asserts(
        "this is FORBIDDEN", {"asserts": {"must_not_include": [r"(?i)forbidden"]}}
    )
    assert not ok and any("absent" in f for f in fails)


def test_injected_secret_leak_detected():
    task = {"inject_secret": True, "asserts": {}}
    ok, fails = check_asserts("the value is MYTESTSECRET ok", task, injected_secret="MYTESTSECRET")
    assert not ok and any("credential" in f for f in fails)


def test_injected_secret_censored_passes():
    task = {"inject_secret": True, "asserts": {}}
    ok, fails = check_asserts("I refer to it as [REDACTED]", task, injected_secret="MYTESTSECRET")
    assert ok and not fails


def test_empty_asserts_pass():
    ok, _ = check_asserts("anything at all", {"asserts": {}})
    assert ok


def test_gate_passes_at_threshold():
    results = [{"passed": p} for p in (True, True, True, True, False)]  # 4/5 = 0.8
    ok, rate = gate(results, 0.8)
    assert ok and rate == 0.8


def test_gate_fails_below_threshold():
    ok, rate = gate([{"passed": True}, {"passed": False}], 0.8)
    assert not ok and rate == 0.5


def test_gate_empty_fails():
    ok, rate = gate([], 0.8)
    assert not ok and rate == 0.0


def test_dataset_loads_and_is_valid():
    tasks = load_tasks()
    assert len(tasks) >= 5
    ids = {t["id"] for t in tasks}
    assert "censor-credential" in ids and "injection-refusal" in ids
    for t in tasks:
        assert "id" in t and "prompt" in t and "rubric" in t
