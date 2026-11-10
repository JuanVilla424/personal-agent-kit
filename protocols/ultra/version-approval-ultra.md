# 🔐 Version Approval Protocol (Ultra)

**Version**: 1.0.1
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

❌ NEVER bump version without explicit user approval.
❌ NEVER auto-bump on "looks good" or similar vague confirmations.
❌ NEVER bump MAJOR or MINOR when PATCH is the correct scope.

---

## ✅ Rules

**Approval keywords (exact match required):**

```
"apruebo" | "aprobado" | "sí" | "yes" | "bump to X.Y.Z" | "ok, bump"
```

**Bump scope table:**

| Change           | Bump  | Example         |
| ---------------- | ----- | --------------- |
| Bug fix / hotfix | PATCH | `1.2.3 → 1.2.4` |
| New feature      | MINOR | `1.2.3 → 1.3.0` |
| Breaking change  | MAJOR | `1.2.3 → 2.0.0` |

**Execution — only after approval keyword received:**

The agent does not run the bump itself. The **user's own commit** carries the `[patch
candidate]` (or equivalent) marker → `bump2version` reads `.bumpversion.cfg` and updates every
tracked file. Agent may preview only:

```bash
.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]
.claude/scripts/validate-post-update.sh
```

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS
