#!/usr/bin/env python3
"""seed_memory.py — load the initial SHARED memory (project conventions).

Seeds the central memory with the team's core conventions (seed_memories.json)
through the memory service, so the personalization layer starts with the real
shared knowledge instead of empty. User-specific memories are added later by
each user via `memory.py add --scope user`.
"""

import json
import os
import sys
from pathlib import Path

import requests

THIS = Path(__file__).resolve()
URL = os.getenv("MEMORY_SERVICE_URL", "http://localhost:7800").rstrip("/")
TOKEN = os.getenv("MEMORY_SERVICE_TOKEN", "")
HEADERS = {"X-Memory-Token": TOKEN} if TOKEN else {}


def main():
    seed_file = THIS.parent / "seed_memories.json"
    items = json.loads(seed_file.read_text(encoding="utf-8"))
    ok = 0
    for m in items:
        try:
            r = requests.post(
                f"{URL}/memory/add",
                json={
                    "text": m["text"],
                    "scope": m.get("scope", "shared"),
                    "user": "",
                    "category": m.get("category", "other"),
                    "source": "stated",
                },
                headers=HEADERS,
                timeout=10,
            )
            if r.ok:
                ok += 1
        except requests.exceptions.RequestException:
            print("⚠️  memory service not available", file=sys.stderr)
            sys.exit(1)
    print(f"✅ {ok}/{len(items)} seed memories (shared) loaded")


if __name__ == "__main__":
    main()
