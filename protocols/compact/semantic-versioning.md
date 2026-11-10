# Semantic Versioning Protocol (Compact)

**Version**: 1.0.2

## Absolute Prohibitions

**IMMEDIATELY REJECT:**

- ❌ version: 0.x.x (ANY 0.x.x version)
- ❌ version: 1.0.0 (specifically 1.0.0)
- ❌ **Version**: 0.x.x (in markdown)
- ❌ **Version**: 1.0.0 (in markdown)

**ALWAYS START AT:** version: 1.0.1

## SemVer Rules

**Format:** MAJOR.MINOR.PATCH

| Change Type               | Bump  | Example     |
| ------------------------- | ----- | ----------- |
| Bug fixes                 | PATCH | 1.2.3→1.2.4 |
| New features (compatible) | MINOR | 1.2.3→1.3.0 |
| Breaking changes          | MAJOR | 1.2.3→2.0.0 |

## Version Management

**Single source of truth:**

```
.bumpversion.cfg (current_version = X.Y.Z)
```

**Tracked files (each a `[bumpversion:file:...]` section in `.bumpversion.cfg`):**

- pyproject.toml
- README.md
- .bmadrc.yaml

**Manual update:**

- CHANGELOG.md (never auto-update)

## Version Operations

**Bump (requires user approval — never agent-initiated):**

Triggered by `[patch candidate]` (or equivalent) in the **user's own commit message** →
`bump2version` runs, updates every tracked file together, commits.

**Preview only (safe, no changes):**

```bash
.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]
```

## Pre-Write Validation

**BEFORE Write/Edit, CHECK content for:**

- No "version: 1.0.0" or "version: 0.x.x"
- No "**Version**: 1.0.0" or "**Version**: 0.x.x"
- No "-v1", "-v2", "-v3" in filenames

**If found: FIX before writing.**

## Violations = Task Halt

Using prohibited versions causes immediate task halt.
