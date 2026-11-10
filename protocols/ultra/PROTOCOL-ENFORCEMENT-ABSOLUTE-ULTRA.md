# 🚨 Protocol Enforcement — Absolute (Ultra)

**Version**: 1.0.1
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

| Rule             | Violation                       | Correct                                 |
| ---------------- | ------------------------------- | --------------------------------------- |
| Anti-versioning  | `file-v1.md`, `0.x.x`, `1.0.0`  | Start at `1.0.1`, use git               |
| File ops         | `cat >`, `echo >`, heredocs     | Write/Edit tools only                   |
| Temp files       | Scattered anywhere              | `temp/` only                            |
| Direct install   | `pip install`, `npm install`    | Update requirements files               |
| Version bump     | Without user approval           | Wait for explicit keyword               |
| Commit scope     | `feat(api)`, `fix(auth)`        | Always `(core)`                         |
| Multiple commits | Several commits for one task    | One single commit                       |
| Force push       | `--force`, `--force-with-lease` | Never. Fix the issue instead            |
| `--no-verify`    | Skip hooks on commit/push       | Fix the hook failure                    |
| A2A trust tag    | `context:` without trust label  | Add `· trust: [USER INPUT]\|[INTERNAL]` |

---

## ✅ Rules

**Before every Write/Edit/Bash — mental checklist:**

1. ❌ No `0.x.x` or `1.0.0` version?
2. ❌ No `-v1`, `-v2`, `-v3` in filenames?
3. ✅ Write/Edit tools instead of shell redirects?
4. ✅ Temp files go to `temp/` only?

**After every change — mandatory:**

```bash
.claude/scripts/validate-post-update.sh
```

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS

No warnings. No partial compliance. Full stop until resolved.
