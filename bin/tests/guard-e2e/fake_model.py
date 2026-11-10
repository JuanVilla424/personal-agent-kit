#!/usr/bin/env python3
"""fake_model.py — a scripted model server, so the real engines run with no key and no spend.

It answers both APIs the engines speak, streaming: POST /v1/messages (Claude Code) and
POST /v1/chat/completions (OpenCode). Each request that offers the shell tool takes the next step
of the script; the engine runs that tool call for real, so its hooks and plugins judge it. Any
other request (titles, quota probes) gets a plain text answer and no step.

Script: a JSON list of {"tool": "shell"|"write"|"fetch", "input": {...}} steps, then the final
text. Each input is fitted to the schema the engine offers (`path` becomes `file_path` or
`filePath`, a required `prompt` gets a default). Every tool result the engine sends back lands in
--log as one JSON line {"step", "text"}.

Usage: fake_model.py --script steps.json --log results.jsonl --port-file port.txt
"""

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FINAL_TEXT = "done"
# The memory brief this server hands out as memory_service would; seen.txt records whether the
# engine's prompt carried it.
BRIEF_TEXT = "E2E-BRIEF the owner prefers concise answers"
# The name each engine gives each tool, in the order they are tried.
TOOL_NAMES = {
    "shell": ("Bash", "shell", "bash"),
    "write": ("Write", "write"),
    "fetch": ("WebFetch", "webfetch"),
}
# What a script key is called in each engine's schema, and values for required extras.
KEY_ALIASES = {"path": ("file_path", "filePath", "path")}
LOAD_PREFIX = "load_"
REQUIRED_DEFAULTS = {"prompt": "Summarize the page.", "format": "text", "description": "e2e step"}


class Script:
    """The steps left, and what came back from the ones already taken."""

    def __init__(self, steps: list[dict], log_path: Path) -> None:
        self.steps = steps
        self.log_path = log_path
        self.taken = 0
        self.final_text = FINAL_TEXT
        self.output_tokens = 1  # --usage raises it, to make the engine's cost cap trip
        self.loaded: set[int] = set()  # steps whose deferred tool was already asked for
        self.seen_results: set[str] = set()
        self.lock = threading.Lock()

    def record(self, results: list[tuple[str, str]]) -> None:
        """Log each tool result once: every request repeats the whole conversation."""
        with self.lock, self.log_path.open("a", encoding="utf-8") as log:
            for call_id, text in results:
                if call_id.startswith(LOAD_PREFIX):
                    continue  # loading a deferred tool is not a step
                if call_id not in self.seen_results:
                    self.seen_results.add(call_id)
                    step = int(call_id.rsplit("_", 1)[-1])
                    log.write(json.dumps({"step": step, "text": text}) + "\n")

    def next_step(self, tools: dict[str, dict]) -> dict | None:
        """The next tool call, spelled with the name and keys this engine offers, or None."""
        with self.lock:
            while self.taken < len(self.steps):
                step = self.steps[self.taken]
                if "final" in step:  # the answer every later request gets
                    self.final_text = step["final"]
                    self.taken += 1
                    continue
                name = next((n for n in TOOL_NAMES[step["tool"]] if n in tools), None)
                # Claude Code defers some tools: ToolSearch loads one, then it is offered
                if name is None and "ToolSearch" in tools and self.taken not in self.loaded:
                    self.loaded.add(self.taken)
                    query = {"query": f"select:{TOOL_NAMES[step['tool']][0]}", "max_results": 1}
                    return {
                        "id": f"{LOAD_PREFIX}{self.taken}",
                        "name": "ToolSearch",
                        "input": query,
                    }
                call_id = f"call_{self.taken}"
                self.taken += 1
                if name:
                    return {
                        "id": call_id,
                        "name": name,
                        "input": fit_input(tools[name], step["input"]),
                    }
                # the engine does not offer this tool: say so in the log and go on
                with self.log_path.open("a", encoding="utf-8") as log:
                    offered = ", ".join(sorted(tools))
                    note = f"NOT OFFERED: no {step['tool']} tool among {offered}"
                    log.write(json.dumps({"step": self.taken - 1, "text": note}) + "\n")
            return None


def fit_input(schema: dict, wanted: dict) -> dict:
    """The script's input with the keys this engine's tool schema names."""
    props = schema.get("properties") or {}
    fitted = {}
    for key, value in wanted.items():
        name = next((n for n in KEY_ALIASES.get(key, (key,)) if n in props), None)
        if name:
            fitted[name] = value
    for name in schema.get("required") or []:
        if name not in fitted and name in REQUIRED_DEFAULTS:
            fitted[name] = REQUIRED_DEFAULTS[name]
    return fitted


def _text_of(content) -> str:
    """The plain text of a message's content, a string or a list of blocks."""
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") for b in content or [] if isinstance(b, dict))


def anthropic_results(messages: list[dict]) -> list[tuple[str, str]]:
    found = []
    for message in messages:
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append((block["tool_use_id"], _text_of(block.get("content"))))
    return found


def openai_results(messages: list[dict]) -> list[tuple[str, str]]:
    return [
        (m["tool_call_id"], _text_of(m.get("content"))) for m in messages if m.get("role") == "tool"
    ]


def anthropic_stream(
    call: dict | None, final_text: str = FINAL_TEXT, output_tokens: int = 1
) -> list[tuple[str, dict]]:
    """The SSE events of one Anthropic streaming answer."""
    usage = {"input_tokens": 1, "output_tokens": output_tokens}
    message = {
        "id": "msg_fake",
        "type": "message",
        "role": "assistant",
        "content": [],
        "model": "fake",
        "stop_reason": None,
        "stop_sequence": None,
        "usage": usage,
    }
    events = [("message_start", {"type": "message_start", "message": message})]
    if call:
        block = {"type": "tool_use", "id": call["id"], "name": call["name"], "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(call["input"])}
        stop_reason = "tool_use"
    else:
        block = {"type": "text", "text": ""}
        delta = {"type": "text_delta", "text": final_text}
        stop_reason = "end_turn"
    events += [
        (
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": block},
        ),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": output_tokens},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    return events


def openai_stream(call: dict | None) -> list[dict]:
    """The chunks of one OpenAI streaming answer."""

    def chunk(delta: dict, finish: str | None = None) -> dict:
        return {
            "id": "chatcmpl-fake",
            "object": "chat.completion.chunk",
            "created": 0,
            "model": "fake",
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    if call:
        function = {"name": call["name"], "arguments": json.dumps(call["input"])}
        tool_call = {"index": 0, "id": call["id"], "type": "function", "function": function}
        return [
            chunk({"role": "assistant", "tool_calls": [tool_call]}),
            chunk({}, "tool_calls"),
        ]
    return [chunk({"role": "assistant", "content": FINAL_TEXT}), chunk({}, "stop")]


class Handler(BaseHTTPRequestHandler):
    server_version = "fake-model"

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        pass  # the harness reads --log, not this

    def _send_sse(self, lines: list[str]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write("".join(lines).encode("utf-8"))

    def do_POST(self):  # pylint: disable=invalid-name
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"
        body = json.loads(raw)
        script: Script = self.server.script  # type: ignore[attr-defined]
        if BRIEF_TEXT.encode() in raw and self.server.seen_path:  # type: ignore[attr-defined]
            self.server.seen_path.write_text("brief\n", encoding="utf-8")  # type: ignore[attr-defined]
        tools = body.get("tools") or []
        if self.path.split("?")[0].endswith("/messages/count_tokens"):
            self._send_json({"input_tokens": 1})
        elif self.path.split("?")[0].endswith("/v1/messages"):
            script.record(anthropic_results(body.get("messages") or []))
            schemas = {t.get("name", ""): t.get("input_schema") or {} for t in tools}
            call = script.next_step(schemas) if "Bash" in schemas else None
            events = anthropic_stream(call, script.final_text, script.output_tokens)
            self._send_sse([f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events])
        elif self.path.split("?")[0].endswith("/chat/completions"):
            script.record(openai_results(body.get("messages") or []))
            schemas = {
                t.get("function", {}).get("name", ""): t.get("function", {}).get("parameters") or {}
                for t in tools
            }
            call = script.next_step(schemas) if schemas else None
            lines = [f"data: {json.dumps(c)}\n\n" for c in openai_stream(call)]
            self._send_sse(lines + ["data: [DONE]\n\n"])
        else:
            self._send_json({"error": {"message": "not found"}}, 404)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # pylint: disable=invalid-name
        if self.path.startswith("/memory/brief"):
            self._send_json({"memories": [{"category": "style", "text": BRIEF_TEXT}]})
            return
        self._send_json({"data": []})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--script", required=True, type=Path)
    ap.add_argument("--log", required=True, type=Path)
    ap.add_argument("--port-file", required=True, type=Path)
    ap.add_argument("--project", default="", help="replaces {project} in the script")
    ap.add_argument(
        "--seen", type=Path, default=None, help="written when a prompt carries the brief"
    )
    ap.add_argument("--usage", type=int, default=1, help="output tokens each answer reports")
    args = ap.parse_args()

    script = args.script.read_text(encoding="utf-8").replace("{project}", args.project)
    steps = json.loads(script)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.script = Script(steps, args.log)  # type: ignore[attr-defined]
    server.seen_path = args.seen  # type: ignore[attr-defined]
    server.script.output_tokens = args.usage  # type: ignore[attr-defined]
    args.port_file.write_text(str(server.server_address[1]), encoding="utf-8")
    server.serve_forever()


if __name__ == "__main__":
    main()
