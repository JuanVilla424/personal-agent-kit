# 🔖 Semantic Versioning Protocol (Ultra)

**Version**: 1.0.2
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

❌ `0.x.x` — never start below 1.0.1
❌ `1.0.0` — reserved, never use as starting version
❌ `-v1`, `-v2` filenames — use git history instead
❌ Bump without explicit user approval

---

## ✅ Rules

**Starting version:** always `1.0.1`

**Bump table:**

| Change type     | Bump  | Example         |
| --------------- | ----- | --------------- |
| Bug fix / patch | PATCH | `1.2.3 → 1.2.4` |
| New feature     | MINOR | `1.2.3 → 1.3.0` |
| Breaking change | MAJOR | `1.2.3 → 2.0.0` |

**Source of truth:** `.bumpversion.cfg` (`current_version = X.Y.Z`)

**Auto-synced files** (each a `[bumpversion:file:...]` section): `pyproject.toml`,
`README.md`, `.bmadrc.yaml`

**Manual update required:** `CHANGELOG.md`

**Bump trigger (requires user approval, never agent-initiated):** `[patch candidate]` marker
in the **user's own commit** → `bump2version` runs. Agent may preview only:

```bash
.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]
```

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS
