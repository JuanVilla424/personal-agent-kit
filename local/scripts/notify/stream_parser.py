import json
from asyncio import StreamReader
from typing import AsyncIterator


async def stream_events(stdout: StreamReader) -> AsyncIterator[dict]:
    """Yield parsed JSONL events from claude -p --output-format stream-json stdout."""
    async for raw in stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def extract_text_delta(event: dict) -> str:
    """Pull incremental text from a content_block_delta event."""
    if event.get("type") != "content_block_delta":
        return ""
    delta = event.get("delta", {})
    if delta.get("type") == "text_delta":
        return delta.get("text", "")
    return ""


def extract_tool_name(event: dict) -> str | None:
    """Return tool name when a tool_use block starts, else None."""
    if event.get("type") != "content_block_start":
        return None
    block = event.get("content_block", {})
    if block.get("type") == "tool_use":
        return block.get("name")
    return None


def is_final(event: dict) -> bool:
    """True when the complete assistant turn has finished."""
    return event.get("type") == "message_stop"
