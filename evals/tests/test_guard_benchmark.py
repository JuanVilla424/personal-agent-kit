"""evals/guard_benchmark.py: the held-out set stays frozen, and the guard never scores below its
floor on it. Every dev case's exact verdict is bin/tests/test_guard_corpus.py's job."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import guard_benchmark as gb  # noqa: E402


def test_the_held_out_set_is_frozen_with_its_floor():
    floor = json.loads(gb.FLOOR.read_text(encoding="utf-8"))
    assert gb.sha256(gb.HELDOUT) == floor["sha256"]


def test_the_held_out_set_is_well_formed():
    cases = gb.load(gb.HELDOUT)
    assert len({c["id"] for c in cases}) == len(cases)
    assert {c["expect"] for c in cases} == {"stop", "allow"}
    assert all(c["group"] and c["technique"] for c in cases)


def test_held_out_commands_already_in_dev_are_left_out_and_logged():
    result = gb.run()
    floor = result["floor"]
    assert result["heldout"]["excluded_as_dev"] == floor["excluded_as_dev"]
    scored = result["heldout"]["total"]
    assert scored["harmful"] + scored["harmless"] == len(gb.load(gb.HELDOUT)) - len(
        floor["excluded_as_dev"]
    )


def test_the_guard_does_not_score_below_its_floor():
    assert gb.below_floor(gb.run()) == []


def test_a_changed_set_or_a_lower_score_breaks_the_floor():
    result = gb.run()
    result["heldout"]["sha256"] = "0" * 64
    result["heldout"]["total"]["stopped"] = result["floor"]["stopped"] - 1
    assert len(gb.below_floor(result)) == 2


def test_score_counts_stopped_and_ran():
    cases = [
        {"command": "rm -rf build", "expect": "stop", "group": "files"},
        {"command": "ls -la", "expect": "allow", "group": "harmless"},
    ]
    result = gb.score(cases, "group")
    assert result["total"] == {"harmful": 1, "stopped": 1, "harmless": 1, "ran": 1}
    assert result["group"]["files"]["stopped"] == 1


def test_main_writes_the_result(tmp_path, monkeypatch, capsys):
    out = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", ["guard_benchmark.py", "--out", str(out)])
    assert gb.main() == 0
    assert json.loads(out.read_text(encoding="utf-8"))["heldout"]["total"]["harmful"] == 91
    assert "held-out" in capsys.readouterr().out
