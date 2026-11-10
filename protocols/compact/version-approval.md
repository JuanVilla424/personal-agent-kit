# Version Approval Protocol (Compact)

**Version**: 1.0.1

## Absolute Rule

**NEVER bump version without explicit user approval.**

## Approval Keywords (case-insensitive)

- "apruebo"
- "aprobado"
- "sí"
- "yes" (in version context)
- "bump to X.Y.Z"
- "ok, bump"

## Proposal Format

When recommending version bump:

```
🔢 **Version Bump Recommended**

Current: X.Y.Z
Recommended: A.B.C
Type: [PATCH|MINOR|MAJOR]

Changes:
- [List changes]

Classification: [Reason for bump type]

Do you approve this version bump?
```

## Decision Matrix

| Change Type               | Bump Type | Example     |
| ------------------------- | --------- | ----------- |
| Bug fixes only            | PATCH     | 1.2.3→1.2.4 |
| New features (compatible) | MINOR     | 1.2.3→1.3.0 |
| Breaking changes          | MAJOR     | 1.2.3→2.0.0 |

## If User Declines

- Acknowledge
- Continue without bump
- Can propose again later

## If User Approves

The agent never runs the bump. It happens when the **user's own commit** carries the
`[patch candidate]` (or equivalent) marker → `bump2version` reads `.bumpversion.cfg` and
updates every tracked file (`pyproject.toml`, `README.md`, `.bmadrc.yaml`, etc.) together.
Agent may preview only: `.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]`

## Violations = Task Halt

Bumping version without approval causes immediate task halt.
