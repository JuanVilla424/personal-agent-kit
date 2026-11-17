#!/usr/bin/env python3
"""memory.py — client for the local agent-memory service.

Used by users and agents alike. Sends TEXT over HTTP to the memory service
(the single writer); no write-key, no embedding model needed locally. If the
service is unreachable (not running / not deployed yet) it degrades gracefully:
warns and exits 0 — the agent keeps working without the personalization layer,
never blocks.

  memory.py add "use tabs, not spaces" --scope user --category style
  memory.py add "corporate color #1B3A5C" --scope shared --category business
  memory.py add "laptop: Framework 13" --state-key laptop   # replaces the older laptop fact
  memory.py search "how do I format the code"
  memory.py brief                                           # what a session starts with
  memory.py forget <id>
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Always load the repo-root .env (same as config.py) so the MEMORY_SERVICE_* vars are
# set no matter where memory.py is invoked from. Repo root = parents[3] of this file.
load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)

# 100% local — one memory_service handles both scopes. "scope" is just a field in the
# request body the server uses to segment shared vs. personal storage, not a routing
# decision made here (there is no central tier in this fork — see memory-protocol.md).
LOCAL_URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:7800").rstrip("/")
TOKEN = os.getenv("MEMORY_SERVICE_TOKEN", "")
USER = os.getenv("PAK_INVOKED_BY", "") or getpass.getuser()
HEADERS = {"X-Memory-Token": TOKEN} if TOKEN else {}

TIMEOUT = 10


def cmd_add(a):
    r = requests.post(
        f"{LOCAL_URL}/memory/add",
        json={
            "text": a.text,
            "scope": a.scope,
            "user": USER,
            "category": a.category,
            "source": "inferred" if a.inferred else "stated",
            "state_key": getattr(a, "state_key", ""),
        },
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    d = r.json()
    print(f"✅ remembered [{d['scope']}/{d['category']}] id={d['id']}")


def cmd_search(a):
    r = requests.get(
        f"{LOCAL_URL}/memory/search",
        params={"q": a.query, "user": USER, "k": a.k},
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if not results:
        print("(no relevant memories)")
        return
    for m in results:
        tag = "👤" if m.get("scope") == "user" else "🏢"
        src = "" if m.get("source") == "stated" else " ~inferred"
        print(
            f"  {tag} [{m.get('score', 0):.2f}] {m.get('category', '?')}{src}: {m.get('text', '')}"
        )


def cmd_brief(_a):
    """The session-start brief, as Markdown: nothing at all when there is no memory yet."""
    r = requests.get(
        f"{LOCAL_URL}/memory/brief", params={"user": USER}, headers=HEADERS, timeout=TIMEOUT
    )
    r.raise_for_status()
    memories = r.json().get("memories", [])
    if not memories:
        return
    print("# What you remember about this user (memory brief; search for more with memory_search)")
    for m in memories:
        print(f"- [{m.get('category', 'other')}] {m.get('text', '')}")


def cmd_consolidate(_a):
    """The nightly pass: near-duplicates are marked replaced by their newest version."""
    r = requests.post(f"{LOCAL_URL}/memory/consolidate", headers=HEADERS, timeout=TIMEOUT * 6)
    r.raise_for_status()
    print(f"consolidated: {r.json().get('merged', 0)} duplicates marked replaced")


def cmd_forget(a):
    r = requests.post(
        f"{LOCAL_URL}/memory/forget", json={"id": a.id}, headers=HEADERS, timeout=TIMEOUT
    )
    r.raise_for_status()
    print(f"🗑️  forgot {a.id}")


def main():
    parser = argparse.ArgumentParser(description="Agent memory client")
    sub = parser.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="Save a memory")
    p_add.add_argument("text")
    p_add.add_argument("--scope", choices=["user", "shared"], default="user")
    p_add.add_argument(
        "--category", choices=["security", "style", "systems", "business", "other"], default="other"
    )
    p_add.add_argument(
        "--inferred", action="store_true", help="the agent inferred it (you didn't say it yourself)"
    )
    p_add.add_argument(
        "--state-key", default="", help="a fact that changes: replaces the memory with this key"
    )

    p_search = sub.add_parser("search", help="Search relevant memories")
    p_search.add_argument("query")
    p_search.add_argument("--k", type=int, default=5)

    p_forget = sub.add_parser("forget", help="Forget a memory by id")
    p_forget.add_argument("id")

    sub.add_parser("brief", help="Print what a session starts with")
    sub.add_parser("consolidate", help="Mark near-duplicate memories replaced by the newest")

    args = parser.parse_args()
    handlers = {
        "add": cmd_add,
        "search": cmd_search,
        "forget": cmd_forget,
        "brief": cmd_brief,
        "consolidate": cmd_consolidate,
    }
    if args.cmd not in handlers:
        parser.print_help()
        return
    try:
        handlers[args.cmd](args)
    except requests.exceptions.RequestException:
        # Graceful: memory layer optional. Never block the agent.
        print(
            "⚠️  memory unavailable (service not responding) — continuing without personalization",
            file=sys.stderr,
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
