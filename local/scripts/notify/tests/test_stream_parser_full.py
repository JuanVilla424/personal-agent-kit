"""Coverage for core/stream_parser.py — tool-name extraction, bad payloads, streaming."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import stream_parser as sp  # noqa: E402


def test_extract_text_delta_handles_bad_content():
    # content is not a list → block.get raises → swallowed → ""
    assert sp.extract_text_delta({"type": "assistant", "message": {"content": "notalist"}}) == ""


def test_extract_tool_name_with_path():
    ev = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "/x"}}]
        },
    }
    assert sp.extract_tool_name(ev) == "Read(/x)"


def test_extract_tool_name_without_path():
    ev = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]},
    }
    assert sp.extract_tool_name(ev) == "Bash"


def test_extract_tool_name_non_assistant_event():
    assert sp.extract_tool_name({"type": "result"}) == ""


def test_extract_tool_name_handles_bad_content():
    assert sp.extract_tool_name({"type": "assistant", "message": {"content": 123}}) == ""


async def test_stream_events_parses_and_skips_noise():
    async def gen():
        for line in [b'{"a": 1}\n', b"\n", b"not-json\n", b'{"b": 2}\n']:
            yield line

    events = [e async for e in sp.stream_events(gen())]
    assert events == [{"a": 1}, {"b": 2}]
