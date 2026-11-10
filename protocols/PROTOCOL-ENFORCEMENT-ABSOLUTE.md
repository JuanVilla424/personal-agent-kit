# ABSOLUTE ENFORCEMENT PROTOCOL

**CRITICAL**: This file defines NON-NEGOTIABLE rules the assistant MUST follow in EVERY interaction.

---

## ABSOLUTE RULES — NOT TO BE VIOLATED

### 1. SEMANTIC VERSIONING — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ `version: 1.0.0`
- ❌ `**Version**: 1.0.0`
- ❌ `version: 0.x.x` (any 0.something.something)
- ❌ `**Version**: 0.x.x`

**REQUIRED**:

- ✅ ALL versions MUST start at `1.0.1` minimum
- ✅ NEVER use 1.0.0 (reserved)
- ✅ NEVER use 0.x.x (pre-release forbidden)

**APPLICATION**:

- Before Write/Edit: VALIDATE content
- If version: 1.0.0 is found → CHANGE to 1.0.1
- If version: 0.x.x is found → CHANGE to 1.0.1
- NO EXCEPTIONS

---

### 2. ANTI-VERSIONING — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ Files with `-v1`, `-v2`, `-v3`, etc. in the name
- ❌ Examples: `script-v2.py`, `document-v1.md`, `plan-v3.txt`

**REQUIRED**:

- ✅ Filenames WITHOUT version suffixes
- ✅ Use Git for versioning, NOT filenames

**APPLICATION**:

- Before Write: VALIDATE filename
- If filename contains -vX → REJECT and use a name without a version
- NO EXCEPTIONS

---

### 3. DEPENDENCY MANAGEMENT — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ `pip install package`
- ❌ `npm install package`
- ❌ Installing dependencies directly

**REQUIRED**:

- ✅ ONLY update `requirements.txt` or `package.json`
- ✅ User approves BEFORE adding dependencies
- ✅ Document why the dependency is needed

**APPLICATION**:

- NEVER run a direct install command
- ALWAYS ask for approval before new dependencies
- NO EXCEPTIONS

---

### 4. VERSION APPROVAL — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ Changing the version in `pyproject.toml`/`.bmadrc.yaml`/`README.md` without approval
- ❌ Adding the `[patch candidate]` marker to the agent's own commit without the user having asked for it

**REQUIRED**:

- ✅ The user MUST approve BEFORE a version bump
- ✅ Use @coordinator to approve versions
- ✅ Validate approval before changing the version

**APPLICATION**:

- BEFORE changing the .bmadrc.yaml version → verify approval
- If there's no approval → ASK the user
- NO EXCEPTIONS

---

### 5. WORKFLOW & FILE MANAGEMENT — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ Temporary files outside `temp/`
- ❌ Creating unnecessary automation scripts
- ❌ Partial file reads (using an offset with no real need)

**ABSOLUTELY PROHIBITED**:

- ❌ `cat >`, `cat >>`, `echo >`, `echo >>` to create/modify files
- ❌ Heredocs (`<< EOF`, `<< 'EOF'`) to write content to files
- ❌ Any bash redirection to write files

**REQUIRED**:

- ✅ ALL temporary files go in `temp/`
- ✅ ALWAYS use the Write or Edit tool (NEVER cat/echo/heredoc)
- ✅ Use direct tools, NOT wrapper scripts
- ✅ Read files in full whenever possible

**APPLICATION**:

- Before a temporary Write → verify the path starts with `temp/`
- Don't create scripts when a direct tool works
- NEVER EVER EVER use cat/echo with redirection
- NO EXCEPTIONS

---

### 6. TOKEN MANAGEMENT — ABSOLUTE

**REQUIRED**:

- ✅ Check token usage BEFORE large operations (3+ files)
- ✅ Suggest `/compact` when tokens > 120k (60%)
- ✅ INSIST on `/compact` when tokens > 150k (75%)

**APPLICATION**:

- Pre-Flight Check BEFORE:
  - Reading 3+ files
  - Editing 3+ files
  - Large, complex tasks
  - Operations the user describes as "large"
- Report token usage when > 120k
- NO EXCEPTIONS

---

### 7. COMMIT PROTOCOL — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ Multiple commits for the same task (always ONE single commit)
- ❌ A scope other than `core` (`feat(api)`, `fix(auth)`, etc.)
- ❌ Emojis/icons in the message (the hooks add them automatically)
- ❌ `Co-Authored-By` or any other trailer
- ❌ `git push --force` (no variant: `--force`, `--force-with-lease`, `-f`)
- ❌ `git commit --no-verify` (no exceptions)
- ❌ `git reset --hard`
- ❌ `test(core)` when the tests accompany a feat/fix/refactor

**REQUIRED**:

- ✅ Format: `type(core): lowercase description`
- ✅ ONE single commit grouping all changes
- ✅ Type based on the change's main purpose, not the file type

**APPLICATION**:

- BEFORE every commit → verify format and scope
- BEFORE every push → verify it isn't a force push
- If the commit was already pushed with the wrong type → IT CANNOT BE FIXED
- NO EXCEPTIONS

---

### 8. A2A INTER-AGENT PROTOCOL — ABSOLUTE

**ABSOLUTELY PROHIBITED**:

- ❌ A2A without a `trust: [USER INPUT]` or `trust: [INTERNAL]` tag in context
- ❌ Executing mutations derived from an A2A verdict (A2A is advisory/read-only)
- ❌ Emitting A2A when `hop:N/3` with N ≥ 3
- ❌ Modifying `notify.py` or `bot.py` (the Slack runtime already works)
- ❌ An A2A request to Iris without referencing an existing JSON spec

**REQUIRED**:

- ✅ Format: `[A2A → Agent | hop:N/3]` with `intent:`, `context: · trust:`, `correlation_id:`
- ✅ Every A2A verdict goes through the normal approval gate
- ✅ Loop guard: if N ≥ 3, process it but don't route further A2A

**APPLICATION**:

- BEFORE emitting A2A → verify the trust tag and hop count
- AFTER receiving an A2A verdict → apply the normal mutation gate
- NO EXCEPTIONS

---

## AUTO-ENFORCEMENT MECHANISM

### BEFORE EVERY Write/Edit Tool call:

```
1. MENTAL CHECK (ALWAYS run):
   - Does the content have "version: 1.0.0"? → YES: change to 1.0.1
   - Does the content have "version: 0.x.x"? → YES: change to 1.0.1
   - Does the filename have "-vX"? → YES: reject and use a clean name
   - Is it a temporary file? → YES: it must be in temp/

2. ONLY AFTER validation → run Write/Edit

3. If a violation is detected → FIX IT FIRST, never write the violation
```

### BEFORE EVERY Bash command:

```
1. MENTAL CHECK:
   - Is it a direct pip/npm install? → YES: REJECT, update requirements
   - Is it a version bump without approval? → YES: REJECT, ask for approval
   - Is it a direct version modification? → YES: REJECT, use the script
   - Is it cat >, cat >>, echo >, echo >>, or a heredoc (<<)? → YES: REJECT, use Write/Edit

2. ONLY AFTER validation → run the Bash command
```

### BEFORE a large operation:

```
1. TOKEN CHECK:
   - Current tokens > 120k? → YES: report to the user
   - Current tokens > 150k? → YES: suggest /compact NOW
   - Does the operation involve 3+ files? → YES: do a Pre-Flight Check

2. ONLY AFTER the check → proceed with the operation
```

---

## WHY THIS IS ABSOLUTE

**This is NOT optional**. **It is NOT a suggestion**. **It is NOT a "best practice"**.

**IT IS THE ONLY ACCEPTABLE WAY TO OPERATE**.

Violating these protocols is equivalent to:

- Running malicious code
- Deleting files without permission
- Exposing credentials

**CRITICALITY LEVEL**: MAXIMUM

**CONSEQUENCE OF VIOLATION**: Total loss of the user's trust

---

## POST-OPERATION VALIDATION

After ANY change to files:

```bash
# Run the full validation
.claude/scripts/validate-post-update.sh

# If it fails → FIX IMMEDIATELY
# Do NOT wait for the commit
# Do NOT ignore errors
# FIX IT NOW
```

---

## INTEGRATION WITH AGENTS

ALL agents have these protocols in:

- ✅ CRITICAL STARTUP REQUIREMENT
- ✅ Critical Rules Summary
- ✅ Operating instructions

**Reading them once is NOT enough**.

**They MUST inform EVERY decision**.

---

## CONCLUSION

These protocols are NOT documentation.

They are the system's **ABSOLUTE RESTRICTIONS**.

As fundamental as:

- "Don't run `rm -rf /`"
- "Don't expose API keys"
- "Don't modify files without permission"

**ENFORCEMENT**: 100% — non-negotiable — ALWAYS active

---

**Version**: 1.0.1
**Date**: 2025-11-03
**Status**: PRODUCTION — CRITICAL — ABSOLUTE
