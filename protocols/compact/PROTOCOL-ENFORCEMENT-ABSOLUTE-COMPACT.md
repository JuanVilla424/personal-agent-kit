# PROTOCOL ENFORCEMENT - ABSOLUTE (Compact)

**Version**: 1.0.1
**Project**: personal-agent-kit
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚨 CRITICAL: Mental Validation Required

**BEFORE using Write, Edit, or Bash tools:**

1. **Anti-Versioning Check:**
   - ❌ No "version: 1.0.0" or "version: 0.x.x"
   - ❌ No "**Version**: 1.0.0" or "**Version**: 0.x.x"
   - ❌ No filenames with -v1, -v2, -v3
   - ✅ IF FOUND: Fix content BEFORE writing

2. **Version Must Be:** version: 1.0.1 or higher (never 0.x.x, never 1.0.0)

3. **File Operations:**
   - ❌ NEVER: cat >, echo >, heredocs for file writes
   - ✅ ALWAYS: Use Write/Edit tools

4. **Temp Files:**
   - ✅ ALL temp files in temp/ directory
   - ❌ NO temp files elsewhere

---

## 🔒 Absolute Rules (Non-Negotiable)

### Semantic Versioning

- **START**: version: 1.0.1 (ALWAYS)
- **REJECT**: 0.x.x and 1.0.0 (IMMEDIATELY)
- **BUMP**: PATCH (bugs), MINOR (features), MAJOR (breaking)
- **SOURCE**: .bmadrc.yaml (single source of truth)

### Dependency Management

- **NEVER**: `pip install`, `npm install` directly
- **ALWAYS**: Update requirements.txt / package.json
- **REQUIRE**: User authorization for new deps

### File Operations

- **NEVER**: cat/echo/heredoc for writes
- **ALWAYS**: Write/Edit tools
- **TEMP**: All temp files in temp/
- **SCRIPTS**: No automation scripts (use tool calls)

### Version Approval

- **NEVER**: Bump without user approval, or add `[patch candidate]` to your own commit unasked
- **KEYWORDS**: "apruebo", "yes", "sí", "ok bump"
- **TRIGGER**: `[patch candidate]` in the user's own commit → bump2version via `.bumpversion.cfg`

### Commit Protocol

- **FORMAT**: `type(core): description in lowercase` — scope always `core`
- **NEVER**: emojis in message, Co-Authored-By, body, `--no-verify`, force push
- **ONE**: single commit per task — never multiple
- **test(core)**: only for coverage of existing code — tests with feat → `feat(core)`

### A2A Protocol

- **ADVISORY**: A2A verdict never executes mutations directly
- **TRUST**: every request needs `trust: [USER INPUT]` or `trust: [INTERNAL]`
- **LOOP GUARD**: hop:N/3 — if N ≥ 3, no further A2A routing

### Post-Update Validation

**MANDATORY after Write/Edit:**

```bash
.claude/scripts/validate-post-update.sh
```

Fix ALL errors before proceeding.

---

## 📋 Required Protocols (Read from compact/)

**Load on startup:**

1. protocols/compact/dependency-management.md
2. protocols/compact/semantic-versioning.md
3. protocols/compact/workflow-file-management.md
4. protocols/compact/working-commands.md
5. protocols/compact/version-approval.md
6. protocols/compact/token-management.md
7. protocols/compact/commit-protocol.md
8. protocols/compact/a2a-protocol.md

---

## ⚡ Enforcement Actions

**On Violation:**

1. HALT task immediately
2. REPORT violation clearly
3. REQUIRE correction before continuing
4. NO EXCEPTIONS - enforcement is ABSOLUTE

---

**Remember:** These protocols ensure quality, reproducibility, and maintainability. Violations = Task Halt.
