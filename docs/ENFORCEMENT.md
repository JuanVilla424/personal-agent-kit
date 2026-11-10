# BMAD Protocol Enforcement System

**Version**: 1.0.1
**Date**: 2025-11-03
**Status**: PRODUCTION - MANDATORY

---

## Overview

This document describes the **MANDATORY** enforcement system for BMAD protocols. Unlike
optional AI-tool hooks (which have variable-interpolation limitations), this system gives the
assistant a script with direct file-system access and a clear exit code, executed explicitly
via the Bash tool.

---

## How Enforcement Works

### 1. Validation Script

**Location**: `.claude/scripts/validate-post-update.sh`

**Purpose**: validates BMAD protocol compliance across the whole repo

**Execution**: per the script's own header, the assistant MUST run it **after updating
files** — in practice this also makes it the natural last check before a commit

**Behavior**:

- Exit 0: all validations passed → safe to proceed / commit
- Exit 1: validation failed → BLOCKED, fix the reported errors and run it again

### 2. Agent Integration

Local BMAD personas are the rows of `.bmad/_cfg/agent-manifest.csv` where `module == local` —
today that's the personas under `.bmad/local/*.txt`. The script reads that CSV directly (the
same source of truth `party-mode` itself reads — see
`.claude/skills/bmad-component/SKILL.md`) instead of a hardcoded agent list, so adding or
removing a local persona doesn't require touching the validator.

**What it checks per local agent**: that the persona file references
`PROTOCOL-ENFORCEMENT-ABSOLUTE-COMPACT` or `PROTOCOL-ENFORCEMENT-ABSOLUTE-ULTRA` — i.e. that it
actually loads one of the enforcement tiers, not just the plain protocol docs.

---

## Validations Enforced

### ✅ 1. Anti-Versioning

**Rule**: no filenames ending in `-v1`, `-v2`, etc. (basename-anchored, so a content-derived
slug like a Kubernetes `batch/v1` job name in a memory file isn't false-flagged)

**Excluded**: `.git/`, `node_modules/`, `venv/`/`.venv/`, `temp/` (gitignored scratch), and
`docs/*upgrade*.md` / `docs/*migration*.md`

### ✅ 2. Version Fields

**Rule**: no `**Version**: 1.0.0` / `**Version**: 0.x.x` (or the `version:` equivalent) across
`protocols/*.md`, `docs/*.md`, and root `*.md` — see the
[Semantic Versioning Protocol](../protocols/semantic-versioning.md)

### ✅ 3. `.bmadrc.yaml` Version

Same forbidden-version rule, applied to `.bmadrc.yaml`'s `version:` field.

### ✅ 4. Agent Protocol Loading

See "Agent Integration" above — every local persona must load an ABSOLUTE enforcement tier.

### ✅ 5. Staged Files (git repos only)

Warns — doesn't block — if nothing is staged when the script runs. A reminder, not a gate.

---

## The Other Validator: Anti-Versioning Only

**Location**: `.claude/scripts/validate-no-versioning.sh`

A narrower, standalone check covering just the anti-versioning rule above, usable three ways:

```bash
# Check a specific file
.claude/scripts/validate-no-versioning.sh temp/plans/proposal-v2.md   # exit 1, blocked

# Check from a Claude Code pre-write hook (reads tool_input JSON from stdin)
echo '{"file_path": "proposal-v2.md"}' | .claude/scripts/validate-no-versioning.sh
```

Reach for this one for a single-file check (e.g. wired into a pre-write hook); reach for
`validate-post-update.sh` for the full post-update sweep described above.

---

## Usage

```bash
# After Write/Edit operations, or before committing
.claude/scripts/validate-post-update.sh

# If it fails (exit 1): read the errors, fix them, run it again.
# Do NOT commit while it's failing.
```

---

## Relationship to Git-Level Hooks

This BMAD validator layer is separate from, and complementary to, the git-level hooks wired
into `.pre-commit-config.yaml`. Those come from the `scripts/` directory (`control_commit`,
`commit_msg_version_bump`, `generate_changelog`, `bump_year`, plus the formatting/lint/hygiene
hooks) and run automatically on `git commit` / `git push`. `validate-post-update.sh` and
`validate-no-versioning.sh` are **not** wired into `.pre-commit-config.yaml` — they're
assistant-discipline checks the agent runs directly via Bash, per the protocols above, not an
automated git hook.

---

## Troubleshooting

**Script not found / not executable**:

```bash
chmod +x .claude/scripts/validate-post-update.sh
./.claude/scripts/validate-post-update.sh   # run from the project root
```

**False positive on a versioned-looking filename**: check the exclusions above —
generated/vendored trees and `temp/` are already excluded, and `docs/*upgrade*.md` /
`*migration*.md` are allowed to keep a `vN` in the name.

---

## Related Protocols

- **[Semantic Versioning Protocol](../protocols/semantic-versioning.md)** — version number rules
- **[Version Approval Protocol](../protocols/version-approval.md)** — bump approval workflow
- **[Workflow & File Management](../protocols/workflow-file-management.md)** — source of the
  anti-versioning rule

---

**Document Status**: PRODUCTION
**Last Updated**: 2025-11-03
**Maintained By**: BMAD Framework
