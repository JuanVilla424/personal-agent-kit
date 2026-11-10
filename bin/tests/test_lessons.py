"""bin/lessons.py: each control keeps its incident and its expiry."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))

import lessons  # noqa: E402


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("PAK_LESSONS", str(tmp_path / "lessons.jsonl"))
    monkeypatch.setattr(lessons, "remember", lambda _lesson: False)
    return tmp_path / "lessons.jsonl"


def test_a_lesson_keeps_incident_control_and_expiry(store):
    assert (
        lessons.main(
            [
                "add",
                "--incident",
                "pushed a secret",
                "--control",
                "pre-write-guard",
                "--expires",
                "2027-05-01",
            ]
        )
        == 0
    )
    (saved,) = [json.loads(line) for line in store.read_text().splitlines()]
    assert (saved["incident"], saved["control"], saved["expires"]) == (
        "pushed a secret",
        "pre-write-guard",
        "2027-05-01",
    )


@pytest.mark.parametrize(
    "args",
    [
        ["--incident", "x", "--control", "y"],  # no expiry at all
        ["--incident", "x", "--control", "y", "--expires", "2027-01-01", "--until", "z"],  # both
        ["--incident", "x", "--control", "y", "--expires", "next spring"],  # not a date
        ["--incident", " ", "--control", "y", "--until", "z"],  # empty incident
    ],
)
def test_a_lesson_without_its_parts_is_refused(args, store):
    assert lessons.main(["add", *args]) == 2
    assert not store.exists()


def test_expired_controls_are_listed_and_fail_the_check(store, capsys):
    lessons.add("old incident", "old control", expires="2020-01-01")
    lessons.add("open incident", "open control", until="the API is retired")
    assert lessons.main(["expired"]) == 1
    out = capsys.readouterr().out
    assert "EXPIRED" in out and "old control" in out and "open control" not in out
    assert lessons.main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "until the API is retired" in listed


def test_no_lessons_is_not_an_error(capsys):
    assert lessons.main(["list"]) == 0
    assert "none yet" in capsys.readouterr().out
    assert lessons.main(["expired"]) == 0


def test_a_condition_is_never_expired_by_the_script():
    assert not lessons.is_expired({"expires": "", "until": "x"}, date(2099, 1, 1))
    assert lessons.is_expired({"expires": "2026-01-01"}, date(2026, 1, 1))


def test_remember_writes_a_security_memory_through_the_cli(monkeypatch, tmp_path):
    monkeypatch.undo()  # the real remember
    calls = []

    def fake_run(argv, **_kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="✅ remembered [user/security] id=x")

    monkeypatch.setattr(lessons.subprocess, "run", fake_run)
    assert lessons.remember({"incident": "a", "control": "b"}) is True
    assert calls and calls[0][-2:] == ["--category", "security"]
    monkeypatch.setattr(lessons, "MEMORY_CLI", tmp_path / "missing.py")
    assert lessons.remember({"incident": "a", "control": "b"}) is False
