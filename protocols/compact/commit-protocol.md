# Commit Protocol (Compact)

**Version**: 1.0.1

## Format

```
type(core): description in lowercase
```

Scope is **always** `core`. One line. No body. No co-author. No emojis (hooks add them on push).

## Types

| Type       | When                                                     |
| ---------- | -------------------------------------------------------- |
| `feat`     | New functionality (tests included → still `feat`)        |
| `fix`      | Bug fix (tests included → still `fix`)                   |
| `refactor` | No functional change (tests included → still `refactor`) |
| `docs`     | Docs only                                                |
| `style`    | Formatting only                                          |
| `test`     | Coverage of EXISTING code only — zero functional change  |
| `chore`    | Maintenance, tooling                                     |

## One Commit Rule

Always one single commit grouping all changes. Never multiple.

## CI Promotion (optional)

Append `[patch candidate]` at end only to trigger `dev → test → prod → main` promotion.

## Absolute Prohibitions

- ❌ `git push --force` (any variant)
- ❌ `git reset --hard`
- ❌ `--no-verify`
- ❌ Amending a pushed commit

## Violations = Task Halt

Wrong type, wrong scope, force push, or multiple commits causes immediate task halt.
