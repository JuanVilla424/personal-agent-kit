# 📦 Dependency Management Protocol (Ultra)

**Version**: 1.0.1
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

❌ NEVER run `pip install`, `npm install`, `yarn add`, or any direct package install command.

❌ NEVER add a dependency without verifying compatibility first.

---

## ✅ Rules

**Workflow — always follow this order:**

| Step | Action                                                                |
| ---- | --------------------------------------------------------------------- |
| 1    | Update the dependency file (`requirements.txt`, `package.json`, etc.) |
| 2    | Explain the need and verify version compatibility                     |
| 3    | Get explicit user approval                                            |
| 4    | User runs the install command themselves                              |

**Compatibility checks before adding:**

- No version conflicts with existing deps
- Confirm the dependency is actually necessary (no bloat)
- Prefer pinned versions (`==`) over ranges (`>=`) for production deps

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS
