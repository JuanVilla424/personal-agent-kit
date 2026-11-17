"""local/hooks/brain-emit.py — what each hook call becomes on the brain page's bus."""

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "brain-emit.py"


def _load():
    spec = importlib.util.spec_from_file_location("brain_emit_under_test", HOOK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


emit = _load()
REGIONS = emit.cortex_map()


def _tool(name: str, **given) -> dict:
    return {"hook_event_name": "PreToolUse", "tool_name": name, "tool_input": given}


def test_a_tool_call_is_one_pulse_through_its_regions():
    pulse = emit.pulse_of(_tool("Bash", command="git  status\n--short"), REGIONS)
    assert pulse == {
        "kind": "tool",
        "text": "Bash · git status --short",
        "path": ["dlpfc", "bg"],
        "side": "",
    }
    assert emit.pulse_of(_tool("Edit", file_path="a.py"), REGIONS)["side"] == "L"


def test_what_a_tool_was_given_is_masked():
    pulse = emit.pulse_of(_tool("Bash", command="curl -H token=abc123 https://x"), REGIONS)
    assert "abc123" not in pulse["text"] and pulse["text"].startswith("Bash · curl")


def test_an_mcp_tool_is_found_by_its_name_without_the_prefix():
    pulse = emit.pulse_of(_tool("mcp__memory__memory_add", text="private"), REGIONS)
    assert pulse["text"] == "memory_memory_add" and pulse["path"] == ["hip"]
    assert "private" not in json.dumps(pulse)


def test_a_tool_the_map_does_not_know_still_pulses():
    unknown = emit.pulse_of(_tool("SomethingNew", anything=1), REGIONS)
    assert unknown["text"] == "SomethingNew" and unknown["path"] == REGIONS["defaults"]["pre"]
    assert emit.pulse_of(_tool("Bash"), {})["path"] == []  # no map at all: the bus falls back
    assert emit.pulse_of({"hook_event_name": "PreToolUse", "tool_name": "Bash"}, {}) is not None


@pytest.mark.parametrize(
    ("event", "kind", "where"),
    [
        ("UserPromptSubmit", "human", "human_prompt"),
        ("PreCompact", "compact", "compact"),
        ("SessionStart", "session", "session_start"),
        ("SessionEnd", "session", "session_end"),
    ],
)
def test_a_session_moment_is_a_pulse_that_never_carries_what_was_typed(event, kind, where):
    pulse = emit.pulse_of({"hook_event_name": event, "prompt": "my secret plan"}, REGIONS)
    assert pulse["kind"] == kind and pulse["path"] == REGIONS["defaults"][where]
    assert "secret" not in pulse["text"]


@pytest.mark.parametrize(
    "hook",
    [
        {"hook_event_name": "PostToolUse", "tool_name": "Bash"},
        {"hook_event_name": "PreToolUse"},
        {},
    ],
)
def test_other_hook_calls_are_not_pulses(hook):
    assert emit.pulse_of(hook, REGIONS) is None


def test_the_map_only_names_regions_the_page_draws():
    paths = [*REGIONS["pre"].values(), *REGIONS["defaults"].values()]
    assert paths and all(set(path) <= emit.brain_bus.REGIONS for path in paths)
    assert set(REGIONS["tool_side"].values()) <= {"L", "R", "both"}


def test_a_missing_map_is_an_empty_one(tmp_path, monkeypatch):
    monkeypatch.setattr(emit, "CORTEX_MAP", tmp_path / "nowhere.json")
    assert emit.cortex_map() == {}


@pytest.mark.parametrize(
    ("typed", "written"),
    [(json.dumps(_tool("Read", file_path="README.md")), 1), ("not json", 0), ("[1, 2]", 0)],
)
def test_the_hook_only_observes(tmp_path, monkeypatch, capsys, typed, written):
    bus = tmp_path / "brain_events.jsonl"
    monkeypatch.setenv("BRAIN_EVENTS_LOG", str(bus))
    monkeypatch.setattr(sys, "stdin", io.StringIO(typed))
    assert emit.main() == 0
    assert capsys.readouterr().out == ""  # a hook that prints could be read as a decision
    lines = bus.read_text(encoding="utf-8").splitlines() if bus.exists() else []
    assert len(lines) == written
    if written:
        assert json.loads(lines[0])["text"] == "Read · README.md"
