# Token Management Protocol - BMAD

**Version**: 1.0.1
**Last Updated**: 2025-11-03
**Status**: Production
**Enforcement**: MANDATORY

---

## 🎯 Purpose

Prevent token budget exhaustion by enforcing proactive monitoring and pre-compact execution.

---

## 🔴 CRITICAL: Pre-Flight Token Check

**BEFORE starting ANY of these operations, the assistant MUST:**

1. **Check token usage** from system warning
2. **Report to user** if > 120k
3. **Suggest /compact** if > 120k
4. **WAIT for user decision** if > 150k

### Operations Requiring Pre-Flight Check

- ✅ Reading multiple files (3+ files)
- ✅ Creating/editing multiple files (3+ files)
- ✅ Large grep/search operations
- ✅ Complex refactoring tasks
- ✅ Agent loading (team-fullstack, etc.)
- ✅ Version bumps
- ✅ Any task user describes as "large" or "complex"

### Pre-Flight Check Template

```markdown
**Token Check**: [X]k/200k ([Y]%)

[IF < 120k] → Proceeding with task
[IF 120-150k] → ⚠️ Recommend /compact after this task
[IF > 150k] → 🚨 Recommend /compact NOW before proceeding. Continue?
```

---

## 📊 Token Usage Thresholds

### Green Zone: 0-120k (0-60%)

- ✅ Continue normally
- ✅ No action needed
- ✅ Update temp/current-context.md periodically

### Yellow Zone: 120k-150k (60-75%)

- ⚠️ **Report token usage** at start of response
- ⚠️ **Suggest /compact** after completing current task
- ⚠️ **Avoid starting large new operations**

### Red Zone: 150k+ (75%+)

- 🚨 **Report token usage** prominently
- 🚨 **SUGGEST /compact NOW** before proceeding
- 🚨 **WAIT for user confirmation** before large operations
- 🚨 If user says continue, proceed but keep responses concise

### Critical Zone: 170k+ (85%+)

- 🔴 **HALT non-essential operations**
- 🔴 **INSIST on /compact**: "Token budget critical at X%. STRONGLY recommend `/compact` before continuing."
- 🔴 **Only proceed with user's explicit approval**
- 🔴 Responses should be minimal - focus on getting user to compact

---

## 🚦 Response Flow

### Every Response Start (Mandatory Check)

```
1. Read system warning for token usage
2. Determine zone (Green/Yellow/Red/Critical)
3. IF Yellow/Red/Critical:
   - Report token usage
   - Suggest /compact
   - IF Critical: Require user decision
4. Proceed or wait based on zone
```

### Example Responses

**Yellow Zone (125k)**:

```
**Token Usage**: 125k/200k (62%)

[Proceed with task]

⚠️  Note: Recommend executing `/compact` after this task completes.
```

**Red Zone (155k)**:

```
🚨 **Token Usage**: 155k/200k (77%)

Token budget is high. Recommend executing `/compact` NOW to preserve context.

**Continue with task or execute /compact first?**
```

**Critical Zone (175k)**:

```
🔴 **CRITICAL: Token Usage at 175k/200k (87%)**

Token budget critically low. STRONGLY recommend `/compact` before proceeding.

**Options**:
1. Execute `/compact` now (recommended)
2. Proceed anyway (not recommended - risk context loss)

**Your choice?**
```

---

## 🛠️ Integration with Hooks

### token-check-reminder.sh Hook

Registered as a `UserPromptSubmit` hook (`local/hooks/token-check-reminder.sh`, via
`local/hooks/install-hooks.py`) — fires on every user prompt and emits an `additionalContext`
system reminder summarizing the Green/Yellow/Red/Critical thresholds below. It replaces the
older `.claude/hooks/check-tokens.sh`, which bundled the same reminder with an unrelated
auto-continue mechanism (superseded by party-mode) and never measured real usage either.

**Assistant Responsibility**:

- Read system warnings (hooks can't see real token usage — no such API exists)
- Follow thresholds defined in this protocol
- Report and suggest to user
- Execute pre-compact skill when appropriate

**Hook's Responsibility**:

- Fire a reminder pointing at this protocol's thresholds on every prompt — nothing else

---

## ⚙️ Pre-Compact Execution

### When to Suggest

- Token usage > 120k (suggest after task)
- Token usage > 150k (suggest before task)
- Token usage > 170k (insist before task)

### User Invokes

User must execute: `/compact`

OR

User says: "guarda contexto", "save context", "compact"

### Execution

When user confirms, the assistant uses pre-compact skill:

1. Updates temp/bmad-state.json
2. Updates temp/current-context.md
3. Creates snapshot (temp/context-snapshot-{timestamp}.md)
4. Creates recovery (temp/context-recovery-{timestamp}.md)
5. Logs compaction

---

## 🚫 What the assistant CANNOT Do

- ❌ Execute /compact automatically (user must invoke)
- ❌ See token usage via hooks (only via system warnings)
- ❌ Force user to compact (can only suggest)

## ✅ What the assistant MUST Do

- ✅ Check tokens before large operations (Pre-Flight Check)
- ✅ Report token usage when in Yellow/Red/Critical zones
- ✅ Suggest /compact proactively
- ✅ Wait for user decision in Critical zone
- ✅ Execute pre-compact skill when user confirms

---

## 📋 Enforcement

**This protocol is MANDATORY**

- The assistant MUST perform Pre-Flight Check before large operations
- The assistant MUST report token usage in Yellow/Red/Critical zones
- The assistant MUST suggest /compact proactively
- The assistant MUST wait for user decision in Critical zone (>170k)

**Validation**:

- User should see token reports when > 120k
- User should receive /compact suggestions when > 150k
- User should see "CRITICAL" warnings when > 170k

---

## 🔗 Related Protocols

- **Workflow & File Management** (1.0.1): temp/ directory usage
- **Working Commands** (1.0.1): /compact command documentation

---

## 📝 Example Workflow

```
User: "Let's refactor the entire codebase"

Pre-Flight Check:
1. Checks tokens: 135k/200k (67%)
2. Zone: Yellow

Response:
⚠️  **Token Usage**: 135k/200k (67%)

This is a large refactoring task. Current token usage is in Yellow zone.

**Recommendation**: Execute `/compact` before starting this large operation?

[Wait for user decision]

User: "/compact"

Assistant: [Executes pre-compact skill]
✅ Context saved. Token usage reduced. Ready to proceed with refactoring.
```

---

**Protocol Version**: 1.0.1
**Last Updated**: 2025-11-03
**Status**: Production - ENFORCED
