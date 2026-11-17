# 🧠 Memory Protocol (Ultra) — local brain

**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

| Rule                             | Violation                                           | Correct                                 |
| -------------------------------- | --------------------------------------------------- | --------------------------------------- |
| Assuming full context            | A layer is down, proceeding as if context were fine | Tell the user, don't assume             |
| Expecting a pre-populated memory | Assuming full memory on a fresh install             | It starts empty and builds up over time |
| Skipping the health check        | Working on memory-dependent tasks without verifying | Check both endpoints before the task    |

---

## ✅ Rules

**Architecture:** 100% local, no central server. Two layers:

| Layer                                                     | What it stores            | If it fails                         |
| --------------------------------------------------------- | ------------------------- | ----------------------------------- |
| Qdrant `agent_memory` (local, :7733)                      | Agent's semantic memory   | Semantic search over past context   |
| Knowledge graph (`~/.claude/projects/<repo-hash>/memory`) | Learned preferences/rules | Inconsistent behavior with the user |

**Health (per task):**

```bash
curl -s http://localhost:7733/collections
curl -s http://localhost:7800/memory/health
```

**No sync:** no server, no replica, no S3 cron. The memory never travels via git and starts
empty on a fresh install — it builds itself up.

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS

A layer being down doesn't block the task, but hiding it IS the violation — telling the user is mandatory.
