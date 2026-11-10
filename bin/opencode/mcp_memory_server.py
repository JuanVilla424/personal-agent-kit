#!/usr/bin/env python3
"""bin/opencode/mcp_memory_server.py — MCP server exposing agent_memory to any MCP client.

Wraps memory_service's HTTP API (local/scripts/memory_index/memory_service.py — add/search/
forget/health) as MCP tools, one tool per endpoint, nothing added or removed. Generic MCP
stdio server — no OpenCode-specific assumptions anywhere in this file. This covers the part
of "memory" that genuinely fits MCP: an on-demand capability the agent can choose to call. It
does NOT make memory load automatically at session start the way Claude Code's KG
(MEMORY.md + feedback_*.md) does — that lives entirely outside this file (Claude Code loads
it natively; OpenCode gets the same file path injected into `instructions` by
build-config.sh, re-read live on every session, no rebuild needed).

Auth: reads MEMORY_SERVICE_URL / MEMORY_SERVICE_TOKEN from .env, exactly like
tts_speak_worker.py and every other client of this same service — never hardcoded.

Two consumers, same file, zero duplication:
  - OpenCode: spawned per bin/opencode/opencode.base.json's `mcp.memory` entry (path resolved
    dynamically by build-config.sh, machine-specific .venv). Its only on-demand memory access.
  - Claude Code: spawned per the repo's `.mcp.json` `memory` entry, using Claude Code's own
    ${CLAUDE_PROJECT_DIR} expansion for the same portability build-config.sh gives OpenCode.
    Fallback/additional path for Claude Code specifically — it already has the native KG
    (MEMORY.md + feedback_*.md, auto-loaded every session); this is for reaching agent_memory
    (the Qdrant-backed semantic memory) as a direct tool call instead of protocol + Bash/curl.

Run (stdio): .venv/bin/python3 <this file>
"""

import os
from pathlib import Path

import requests
from dotenv import load_dotenv
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

MEMORY_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:7700").rstrip("/")
MEMORY_TOKEN = os.getenv("MEMORY_SERVICE_TOKEN", "")
TIMEOUT_SECONDS = 10

mcp = MCPServer("agent-memory")


def _call(method: str, path: str, **kwargs) -> dict:
    """POST/GET to memory_service and turn its errors into ToolError the model can read."""
    headers = {"x-memory-token": MEMORY_TOKEN} if MEMORY_TOKEN else {}
    try:
        resp = requests.request(
            method, f"{MEMORY_URL}{path}", headers=headers, timeout=TIMEOUT_SECONDS, **kwargs
        )
    except requests.RequestException as e:
        raise ToolError(f"memory_service unreachable at {MEMORY_URL}: {e}") from e
    if resp.status_code == 401:
        raise ToolError("memory_service rejected the token — check MEMORY_SERVICE_TOKEN in .env")
    if resp.status_code == 403:
        raise ToolError(resp.json().get("detail", "operation not allowed"))
    if resp.status_code == 404:
        raise ToolError(resp.json().get("detail", "not found"))
    if resp.status_code == 422 and isinstance(resp.json().get("detail"), dict):
        signals = ", ".join(resp.json()["detail"].get("signals", []))
        raise ToolError(
            f"memory_service refused the text: it carries injection signals ({signals})"
        )
    if not resp.ok:
        raise ToolError(f"memory_service returned {resp.status_code}: {resp.text[:200]}")
    return resp.json()


@mcp.tool()
def memory_search(query: str, k: int = 5, include_history: bool = False) -> dict:
    """Search memory (shared + personal) for what is relevant to `query`.

    Hybrid search: meaning and exact words (a name, a port, an ID) both count. A fact that was
    replaced by a newer one is left out unless `include_history` is true.
    """
    params = {"q": query, "k": k}
    if include_history:
        params["include_history"] = "true"
    return _call("GET", "/memory/search", params=params)


@mcp.tool()
def memory_brief() -> dict:
    """The memories a session starts with, most important first: call it once at the start of
    a session when they were not already given to you."""
    return _call("GET", "/memory/brief")


@mcp.tool()
def memory_add(
    text: str, scope: str = "user", category: str = "other", state_key: str = ""
) -> dict:
    """Save a new memory.

    scope="user" (default) is personal, only you search/forget it. scope="shared" is
    visible to any other local consumer of this same memory_service — use it only
    for something worth making accessible beyond your own scope.

    category is one of: security, style, systems, business, other.

    state_key names a fact that changes over time ("laptop", "staging-port"): the new memory
    replaces the one with the same key, which stays readable as history.
    """
    body = {"text": text, "scope": scope, "category": category}
    if state_key:
        body["state_key"] = state_key
    return _call("POST", "/memory/add", json=body)


@mcp.tool()
def memory_forget(memory_id: str) -> dict:
    """Delete a memory by its id (from a previous memory_search or memory_add).

    You can only delete your own personal memories; deleting a shared memory
    requires admin permissions on memory_service and is rejected if you don't have them.
    """
    return _call("POST", "/memory/forget", json={"id": memory_id})


@mcp.tool()
def memory_health() -> dict:
    """Check whether memory_service is reachable and how many memories it has stored."""
    return _call("GET", "/memory/health")


if __name__ == "__main__":
    mcp.run()
