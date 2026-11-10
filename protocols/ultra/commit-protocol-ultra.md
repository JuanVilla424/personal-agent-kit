# 🔏 Commit Protocol (Ultra)

**Version**: 1.0.1
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

| Rule             | Violation                                 | Correct                            |
| ---------------- | ----------------------------------------- | ---------------------------------- |
| One commit only  | Multiple commits for one task             | Single commit grouping all changes |
| Scope            | `feat(api)`, `fix(auth)`, any other scope | Always `(core)`                    |
| Emojis in msg    | `✨ feat(core): ...`                      | `feat(core): ...` (hooks add them) |
| Co-author        | `Co-Authored-By: ...`                     | Nothing — omit trailer entirely    |
| Body/footer      | Multi-line body, issue refs               | Subject line only                  |
| force push       | `--force`, `--force-with-lease`, `-f`     | Never. Period.                     |
| `--no-verify`    | Skipping hooks                            | Fix the hook failure instead       |
| Wrong `test` use | `test(core)` for tests added with a feat  | Use `feat(core)` instead           |

---

## ✅ Rules

**Format — one line:**

```
type(core): description in lowercase
```

**Type selection — by principal purpose:**

| Type       | Use                                                        |
| ---------- | ---------------------------------------------------------- |
| `feat`     | New functionality (its tests → still `feat`)               |
| `fix`      | Bug fix (its tests → still `fix`)                          |
| `refactor` | Improvement without functional change (tests → `refactor`) |
| `docs`     | Documentation only                                         |
| `style`    | Formatting only                                            |
| `test`     | Coverage of EXISTING code only — zero functional change    |
| `chore`    | Maintenance, tooling, config                               |

**CI promotion (optional):**

```
feat(core): add provider support [patch candidate]
```

Append `[patch candidate]` only when promoting `dev → test → prod → main`. Omit otherwise.

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS

Wrong type on a pushed commit cannot be corrected. Do it right the first time.
