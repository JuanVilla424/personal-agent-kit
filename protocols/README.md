# BMAD Agent Protocols

**Version**: 1.0.1
**Last Updated**: 2025-11-02
**Status**: Production
**Scope**: All BMAD agents must enforce these protocols

---

## Overview

This directory contains the core operational protocols that govern all BMAD agents. These protocols are **MANDATORY** and **NON-NEGOTIABLE** for all agents in the system.

### Why Centralized Protocols?

- **Single Source of Truth**: One canonical version of each protocol
- **Easy Maintenance**: Update once, applies to all agents
- **Consistency**: All agents follow identical rules
- **Transparency**: Clear, documented expectations
- **Version Control**: Track protocol evolution over time

---

## Available Protocols

### 1. Dependency Management Protocol

**File**: `dependency-management.md`
**Version**: 1.0.1
**Purpose**: Enforce file-based dependency management (no direct installs)

**Key Rules**:

- 🚫 NO direct `pip install` or `npm install` commands
- ✅ ONLY update `requirements.txt` or `package.json`
- 🔒 User authorization required for new dependencies
- ✅ Compatibility testing mandatory before installation

**When to Apply**: Any task involving dependencies or packages

---

### 2. Semantic Versioning Protocol

**File**: `semantic-versioning.md`
**Version**: 1.0.1
**Purpose**: Enforce SemVer 2.0.0 with mandatory 1.0.1 starting version

**Key Rules**:

- 🚨 ALL projects MUST start at version `1.0.1` (NOT 0.x.x, NOT 1.0.0)
- ✅ PATCH for bug fixes, MINOR for features, MAJOR for breaking changes
- 📝 CHANGELOG.md must be updated with every version change
- ❌ Immediate rejection of any non-compliant versioning

**When to Apply**: Creating new projects, updating versions, releasing features

---

### 3. Workflow & File Management Protocol

**File**: `workflow-file-management.md`
**Version**: 1.0.1
**Purpose**: Enforce clean workflow practices and file organization

**Key Rules**:

- 📁 ALL temporary files MUST go in `temp/` directory
- 🚫 NEVER create scripts to "speed things up" (use direct tool calls)
- 📖 ALWAYS read complete files (never partial/fragmented reads)
- 📝 Maintain `temp/user-messages-history.md` after every user message
- 🔄 Keep `README.md` synchronized with project reality

**When to Apply**: All file operations, workflow management, context handling

---

### 4. Working Commands Protocol

**File**: `working-commands.md`
**Version**: 1.0.1
**Purpose**: Document tested commands to avoid re-testing failures

**Key Rules**:

- ✅ CHECK this protocol before executing unfamiliar commands
- ✅ Use documented working commands and alternatives
- ✅ UPDATE when discovering new working/failing commands
- ❌ Avoid commands known to fail (yq, macOS stat, etc.)

**When to Apply**: Before executing system commands, especially OS-specific ones

---

### 5. Version Approval Protocol

**File**: `version-approval.md`
**Version**: 1.0.1
**Purpose**: Ensure version bumps require user approval

**Key Rules**:

- 🚫 NEVER bump version without user approval
- ✅ ALWAYS propose version bump with clear reasoning
- ✅ WAIT for explicit user consent ("Apruebo", "Yes", etc.)
- ✅ CLASSIFY changes as PATCH/MINOR/MAJOR before proposing

**When to Apply**: When significant changes warrant version bump

---

### 6. Token Management Protocol

**File**: `token-management.md`
**Version**: 1.0.1
**Purpose**: Prevent token exhaustion through proactive monitoring and pre-compact execution

**Key Rules**:

- 🔴 MANDATORY Pre-Flight Check before large operations (3+ files, complex tasks)
- ⚠️ REPORT token usage when > 120k (60%)
- 🚨 SUGGEST /compact when > 150k (75%)
- 🔴 WAIT for user decision when > 170k (85%)
- ✅ Execute pre-compact skill when user confirms

**When to Apply**: Before every large operation, at start of every response

---

### 7. Commit Protocol

**File**: `commit-protocol.md`
**Version**: 1.0.1
**Purpose**: Enforce consistent commit format, one-commit rule, and git safety prohibitions

**Key Rules**:

- 🔏 Format: `type(core): description in lowercase` — scope always `core`
- 🚫 NO emojis in message (hooks add them on push), NO body, NO Co-Authored-By
- 1️⃣ Always one single commit grouping all changes — never multiple
- ❌ NEVER `git push --force`, `git reset --hard`, or `--no-verify`
- 📌 `test(core)` ONLY for coverage of existing code — tests with a feature → `feat(core)`

**When to Apply**: Every time a commit is created or a git push is executed

---

### 8. A2A Inter-Agent Protocol

**File**: `a2a-protocol.md`
**Version**: 1.0.1
**Purpose**: Structured agent-to-agent delegation within IDE party-mode and Slack runtime

**Key Rules**:

- 🔗 Request format: `[A2A → Agent | hop:N/3]` with mandatory `trust:` tag
- 🛡️ Advisory only — A2A verdict NEVER executes mutations directly
- 🔄 Loop guard: `hop:N/3` — if N ≥ 3, no further A2A routing
- 📋 Iris requires existing JSON spec — never invents specs
- 🚫 Do NOT modify Slack runtime (`notify.py`, `bot.py`) — already handles that transport

**When to Apply**: When one agent needs to delegate a bounded task to another agent

---

### 9. Repo Workflow Protocol

**File**: `repo-workflow.md`
**Version**: 1.0.1
**Purpose**: Canonical lifecycle of a repo — approach a task, create/clone, setup, commit, pull/sync, promote, review, resolve conflicts

**Key Rules**:

- 🌿 Correct branch ALWAYS — `dev`, NEVER `main`/`master`
- 🔁 Two-step push — the `validate-commit` hook adds the icon and amends
- 🚫 Promotion ONLY via PR/MR — NEVER push directly to `test`/`prod`/`main`
- 🧩 NEVER edit inside a submodule — the fix goes to the source repo

**When to Apply**: Any task touching a repo — from cloning to promoting to production

---

### 10. Project Creation Roadmap

**File**: `project-creation-roadmap.md`
**Version**: 1.0.1
**Purpose**: Standard methodology for creating any new project/service from template

**Key Rules**:

- ✅ Each step requires explicit user approval before advancing to the next
- 🚫 PROHIBITED: sed, subagents, heredoc, batching when adapting the template — file by file
- ❓ LICENSE: ASK the user which license they want before changing anything
- 🔄 A workflow that doesn't apply gets renamed `.disabled`, NEVER deleted

**When to Apply**: Creating a new repo/service from scratch

---

### 11. Memory Protocol

**File**: `memory-protocol.md`
**Version**: 1.0.1
**Purpose**: Architecture of the agent's local memory — Qdrant + memory_service, no central server

**Key Rules**:

- 🧠 Everything runs locally — no central server, no replicas, no S3 sync
- ⚠️ Qdrant or memory_service down → tell the user, never assume full context
- 📦 Knowledge graph (`MEMORY.md` + sibling files) travels via git, not a separate sync mechanism

**When to Apply**: Any task that depends on accumulated context or cross-session memory

---

## Protocol Enforcement

### For Agents

All BMAD agents must:

1. **Reference protocols explicitly** in their configuration
2. **Enforce rules rigorously** during task execution
3. **Halt immediately** on protocol violations
4. **Report violations clearly** to the user

### For Users

Protocols are designed to:

1. **Prevent common mistakes** (direct installs, version chaos)
2. **Ensure reproducibility** (file-based manifests, complete reads)
3. **Maintain quality** (testing, documentation, validation)
4. **Enable collaboration** (clear conventions, transparency)

---

## Protocol Versioning

Protocols follow Semantic Versioning:

- **PATCH** (1.0.X): Clarifications, typos, minor improvements
- **MINOR** (1.X.0): New rules, additional guidelines (backwards-compatible)
- **MAJOR** (X.0.0): Breaking changes to protocol structure or rules

### Current Versions

| Protocol                   | Version | Last Updated |
| -------------------------- | ------- | ------------ |
| Dependency Management      | 1.0.1   | 2025-10-30   |
| Semantic Versioning        | 1.0.2   | 2025-10-31   |
| Workflow & File Management | 1.0.1   | 2025-10-30   |
| Working Commands           | 1.0.1   | 2025-11-02   |
| Version Approval           | 1.0.1   | 2025-11-02   |
| Token Management           | 1.0.1   | 2025-11-03   |
| Commit Protocol            | 1.0.1   | 2026-06-06   |
| A2A Inter-Agent            | 1.0.1   | 2026-06-06   |
| Repo Workflow              | 1.0.1   | 2026-06-21   |
| Project Creation Roadmap   | 1.0.1   | 2026-06-05   |
| Memory Protocol            | 1.0.1   | 2026-06-21   |

---

## Integration with Agents

### Reference Format (Recommended)

Agents should include this block in their configuration:

```markdown
## MANDATORY PROTOCOLS

**All operations must comply with BMAD Agent Protocols.**

📚 **Protocol Reference**: `protocols/`

**Critical Rules Summary**:

- 🚫 NO direct pip/npm install - only requirements.txt/package.json
- 🔢 ALL projects start at version 1.0.1 (NOT 0.x.x, NOT 1.0.0)
- 📁 ALL temp files go in temp/ directory
- 📖 ALWAYS read complete files (never partial reads)
- 🚫 NEVER create scripts - use direct tool calls
- 🔴 PRE-FLIGHT CHECK before large operations (token check)
- 🚨 SUGGEST /compact when tokens > 150k

**For full details, see:**

- `protocols/dependency-management.md`
- `protocols/semantic-versioning.md`
- `protocols/workflow-file-management.md`
- `protocols/working-commands.md`
- `protocols/version-approval.md`
- `protocols/token-management.md`
- `protocols/commit-protocol.md`
- `protocols/a2a-protocol.md`
- `protocols/repo-workflow.md`
- `protocols/project-creation-roadmap.md`
- `protocols/memory-protocol.md`
- `protocols/decision-protocol.md`
```

### Inline Format (Alternative)

For web bundles or offline agents, protocols can be embedded inline:

```markdown
==================== START: protocols/dependency-management.md ====================
[Full protocol content]
==================== END: protocols/dependency-management.md ====================
```

---

## Contributing to Protocols

### Proposing Changes

1. **Identify the need**: What problem does the change solve?
2. **Draft the change**: Propose specific wording or rule modifications
3. **Test impact**: How does this affect existing agents?
4. **Submit for review**: Get user approval before implementing

### Change Process

1. **Create proposal** in `temp/protocol-proposals/`
2. **Discuss with team** (or user in this case)
3. **Update protocol file** with new version
4. **Update CHANGELOG** in protocol file
5. **Increment version** following SemVer
6. **Update all agents** that reference the protocol

---

## Support & Questions

**Location**: All protocols stored in `/protocols/`
**Owner**: BMAD Project Maintainer
**Contact**: See project README for support channels

---

## Changelog

### Version 1.0.1 (2025-10-30)

- Initial protocol consolidation
- Migrated from inline duplication to centralized files
- Created README with protocol overview
- Established versioning and maintenance guidelines

---

**Remember**: These protocols are not suggestions. They are **MANDATORY REQUIREMENTS** that ensure quality, consistency, and reliability across all BMAD operations.
