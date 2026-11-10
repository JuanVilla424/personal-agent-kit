import json
from typing import AsyncIterator


def extract_text_delta(event: dict) -> str:
    """Returns accumulated text from the latest assistant message event.

    claude -p --output-format stream-json emits {"type":"assistant","message":{...}}
    where each event contains the full accumulated text so far (not a delta).
    """
    try:
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    return block.get("text", "")
    except Exception:
        pass
    return ""


def extract_tool_name(event: dict) -> str:
    try:
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    path = (
                        inp.get("path", inp.get("file_path", "")) if isinstance(inp, dict) else ""
                    )
                    return f"{name}({path})" if path else name
    except Exception:
        pass
    return ""


def is_final(event: dict) -> bool:
    return event.get("type") in ("result", "message_stop")


async def stream_events(stdout) -> AsyncIterator[dict]:
    async for raw in stdout:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue
