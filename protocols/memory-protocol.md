# 🧠 Memory Protocol — local brain

> How the agent's memory works: architecture and health verification.
> Everything here is local — no central server, no fleet, no S3 sync.

---

## Architecture — 100% local

One memory for every engine: `memory_service` over a local Qdrant, reached through the `memory` MCP
tools in Claude Code and OpenCode alike. It does not depend on either engine's own memory folder.
If it is down, the agent works with partial context → **tell the user, don't assume**:

| Piece                                    | What it holds                              | What's lost if it fails            |
| ---------------------------------------- | ------------------------------------------ | ---------------------------------- |
| **Qdrant `agent_memory`** (local, :7633) | Every memory, with its history             | Search and the brief               |
| **`memory_service`** (local, :7700)      | Search, replacement, brief, consolidation  | Everything above, as an API        |
| **Lessons** (`~/.pak/lessons.jsonl`)     | Incidents, their controls and their expiry | Why a control exists, when it ends |

---

## How to use it

- **Start of a session:** both engines get the memory brief before the first message (the most
  important memories within 3,500 characters, security and style first): Claude Code from its
  session start hook, OpenCode from `instructions` (`~/.config/opencode/memory-brief.md`, refreshed
  at each session start). If it is missing, call `memory_brief()` once.
- **Search:** `memory_search(query)` is hybrid: meaning and exact words (a hostname, a port, an ID)
  both count. Search before assuming you know the user's setup.
- **Save:** `memory_add(text, category=…)`, with a category among `security`, `style`,
  `systems`, `business` and `other`. One fact per memory, in plain words.
- **A fact that changes** (the laptop, a port, a schedule): save it with a `state_key`, such as
  `memory_add("Laptop: Framework 13", state_key="laptop")`. It replaces the memory with the same
  key, which stays readable with `include_history`. Nothing is deleted.
- **What is refused:** text with injection signals (instructions to override the rules, hidden
  comments, invisible characters) is not stored; tell the user what you tried to save.

`docs/memory-benchmark.md` measures how often this finds the right fact.

---

## Check before a task

```bash
curl -s http://localhost:7633/collections    # local Qdrant
curl -s http://localhost:7700/memory/health  # local memory_service
```

Run this before any task that depends on accumulated context. If a layer is down, **tell the
user** instead of assuming full context.

---

## No central sync

There is no server, no replica, and no S3 snapshot/restore cron — everything lives on this
machine. A fresh install starts with an empty memory and builds it up as you work; there's nothing
to restore from. Every night at 03:30, `agent-memory-consolidate.timer` marks near-duplicates as
replaced by their newest version (nothing is deleted). To move your memory to another machine, back
up `local/scripts/memory_index/`'s Qdrant volume and `~/.pak/lessons.jsonl` yourself.

## Lessons

When something goes wrong, record the incident, the control that now prevents it and when that
control is reviewed: `python3 bin/lessons.py add --incident "…" --control "…" --expires YYYY-MM-DD`
(or `--until "condition"`). `python3 bin/lessons.py expired` lists the controls due for review.
