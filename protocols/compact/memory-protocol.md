# 🧠 Memory Protocol (Compact)

> Condensed version of `protocols/memory-protocol.md`. 100% local, no central server.

## Architecture — local only

Two layers; if one is down → **tell the user, don't assume**:

- **Qdrant `agent_memory`** (local, :7633) — agent's semantic memory.
- **Knowledge graph** (`~/.claude/projects/<repo-hash>/memory`) — learned preferences/rules.

## Health (per task)

```bash
curl -s http://localhost:7633/collections
curl -s http://localhost:7700/memory/health
```

Run before memory-dependent tasks. A layer down → tell the user, don't assume full context.

## No sync

No central server, no replica, no S3 cron. The **memory never travels via git** — it starts empty
on a fresh install and builds itself up as you work.

## Violation = task halt
