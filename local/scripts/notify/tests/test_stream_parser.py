import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.stream_parser import extract_text_delta, extract_tool_name, is_final


def _assistant_event(content: list) -> dict:
    """Build a claude -p --output-format stream-json assistant event."""
    return {"type": "assistant", "message": {"content": content}}


def test_extract_text_delta():
    event = _assistant_event([{"type": "text", "text": "Hello"}])
    assert extract_text_delta(event) == "Hello"


def test_extract_text_delta_wrong_type():
    event = {"type": "system", "subtype": "init"}
    assert extract_text_delta(event) == ""


def test_extract_text_delta_thinking_ignored():
    # thinking blocks should not return text
    event = _assistant_event([{"type": "thinking", "thinking": "..."}])
    assert extract_text_delta(event) == ""


def test_extract_text_delta_prefers_text_block():
    # if both thinking and text are present, return the text block
    event = _assistant_event(
        [
            {"type": "thinking", "thinking": "internal thought"},
            {"type": "text", "text": "Final answer"},
        ]
    )
    assert extract_text_delta(event) == "Final answer"


def test_extract_tool_name():
    event = _assistant_event(
        [
            {
                "type": "tool_use",
                "name": "Read",
                "input": {"path": "logs/app.log"},
            }
        ]
    )
    assert extract_tool_name(event) == "Read(logs/app.log)"


def test_extract_tool_name_no_path():
    event = _assistant_event([{"type": "tool_use", "name": "Bash", "input": {}}])
    assert extract_tool_name(event) == "Bash"


def test_is_final_result():
    assert is_final({"type": "result"})
    assert is_final({"type": "message_stop"})
    assert not is_final({"type": "assistant"})


def test_extract_text_delta_malformed():
    assert extract_text_delta({}) == ""
    assert extract_text_delta({"type": "assistant"}) == ""
