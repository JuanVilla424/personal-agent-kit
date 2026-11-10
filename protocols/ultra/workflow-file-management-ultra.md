# 📁 Workflow & File Management Protocol (Ultra)

**Version**: 1.0.2
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

| Prohibited                                  | Correct alternative          |
| ------------------------------------------- | ---------------------------- |
| `cat >`, `echo >`, heredocs                 | Write/Edit tools             |
| `sed`, `awk` for file edits                 | Edit tool with exact strings |
| Files named `-v1`, `-old`, `-backup`        | Use git history              |
| Temp files outside `temp/`                  | `temp/` only — gitignored    |
| Automation scripts for one-off ops          | Direct tool calls            |
| Partial file reads when full context needed | Read complete file           |

---

## ✅ Rules

**File operations:**

1. **Create** → Write tool
2. **Modify** → Edit tool (exact string match, not line numbers)
3. **Temp files** → `temp/<name>` always (gitignored)
4. **Read** → full file unless explicitly confirmed partial is sufficient

**After every Write/Edit — mandatory:**

```bash
.claude/scripts/validate-post-update.sh
```

**Anti-versioning:**

❌ `config-v2.yaml` / `script_old.sh` / `backup-2024.md`
✅ One canonical name + git for history

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS
