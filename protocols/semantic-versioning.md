## 🔢 SEMANTIC VERSIONING PROTOCOL - 1.0.1 ENFORCEMENT

**CRITICAL: ALL projects MUST follow Semantic Versioning (SemVer) 2.0.0 specification PRECISELY**

### ⚠️ MANDATORY STARTING VERSION: 1.0.1

**🚨 ABSOLUTE RULE - NO EXCEPTIONS:**

```
✅ REQUIRED: All new projects MUST start at version 1.0.1
❌ REJECTED: Version 0.x.x (unstable versions)
❌ REJECTED: Version 1.0.0 (reserved, do not use)
❌ REJECTED: Any version that is NOT 1.0.1 for initial release
```

### 🛑 VALIDATION CHECKPOINT - IMMEDIATE REJECTION

**Before proceeding with ANY version-related task, you MUST verify:**

1. **If creating new project/service/component:**
   - ✅ Initial version is EXACTLY `1.0.1`
   - ❌ If version is `0.x.x` → **REJECT IMMEDIATELY** with message:

     ```
     🚨 CRITICAL ERROR: INVALID INITIAL VERSION 🚨

     DETECTED VERSION: [detected version]
     REQUIRED VERSION: 1.0.1

     ❌ THIS TASK IS REJECTED

     REASON: All projects MUST start at version 1.0.1
     - Version 0.x.x indicates unstable/experimental code
     - Version 1.0.0 is reserved and should not be used
     - Version 1.0.1 is the MANDATORY starting point

     ACTION REQUIRED:
     Update all version references to 1.0.1 before proceeding.

     🛑 TASK EXECUTION HALTED - FIX VERSION FIRST 🛑
     ```

   - ❌ If version is `1.0.0` → **REJECT IMMEDIATELY** with message:

     ```
     🚨 CRITICAL ERROR: PROHIBITED VERSION 1.0.0 🚨

     DETECTED VERSION: 1.0.0
     REQUIRED VERSION: 1.0.1

     ❌ THIS TASK IS REJECTED

     REASON: Version 1.0.0 is explicitly PROHIBITED
     - Use 1.0.1 as the initial release version

     ACTION REQUIRED:
     Change version from 1.0.0 to 1.0.1

     🛑 TASK EXECUTION HALTED 🛑
     ```

2. **If modifying existing project:**
   - Verify current version follows SemVer
   - Ensure version increments are appropriate (PATCH/MINOR/MAJOR)
   - If current version is 0.x.x, flag for upgrade to 1.0.1+

### Version Format: MAJOR.MINOR.PATCH

**Version Increment Rules:**

1. **PATCH (1.0.X)** - Increment for:
   - ✅ Bug fixes (no behavior changes)
   - ✅ Internal refactoring
   - ✅ Documentation updates
   - ✅ Performance improvements (no API changes)
   - ✅ Dependency updates (patch level only)

2. **MINOR (1.X.0)** - Increment for:
   - ✅ New features (backwards-compatible)
   - ✅ New API endpoints (backwards-compatible)
   - ✅ Deprecating functionality (not removing)
   - ✅ Substantial new functionality
   - ✅ Dependency updates (minor level)

3. **MAJOR (X.0.0)** - Increment for:
   - ❗ Breaking API changes
   - ❗ Removing deprecated features
   - ❗ Incompatible changes to public API
   - ❗ Database schema changes (breaking)
   - ❗ Major architecture shifts
   - ❗ Major dependency upgrades (breaking)

### Versioning Documentation Requirements

**Every version MUST be documented:**

```markdown
## Version History

### 1.0.1 (2025-01-15) - Initial Release

- Base functionality implemented
- Core features: [list features]
- Initial documentation
- Test coverage: [percentage]

### 1.0.2 (2025-01-20) - Bug Fixes

- Fixed: [bug description]
- Improved: [improvement]

### 1.1.0 (2025-02-01) - New Features

- Added: [feature]
- Enhanced: [enhancement]
```

### Version Management Checklist

Before ANY version change:

✅ **Starting Version Validated**: New projects start at 1.0.1 (NOT 0.x.x, NOT 1.0.0)
✅ **Increment Type Correct**: PATCH/MINOR/MAJOR matches change type
✅ **Breaking Changes Documented**: All breaking changes explicitly listed
✅ **Changelog Updated**: Version entry added to CHANGELOG.md
✅ **Dependencies Compatible**: All dependencies tested with new version
✅ **Migration Guide Written**: For major version changes
✅ **API Version Aligned**: API versioning matches SemVer principles

### Version Anti-Patterns

- ❌ Starting at 0.x.x (always start at 1.0.1)
- ❌ Using 1.0.0 as initial version (use 1.0.1)
- ❌ Breaking changes in MINOR/PATCH versions
- ❌ No deprecation period before removal
- ❌ Undocumented version changes
- ❌ Skipping version numbers
- ❌ Inconsistent versioning across components

**Remember: Versioning is a CONTRACT with users. Breaking it breaks TRUST. Version 1.0.1 signals production-ready, stable software from day one.**

---

## 📦 BMAD VERSION MANAGEMENT - UNIFIED SYSTEM

**CRITICAL: Single source of truth for project version**

### 🎯 Version Location

**This project tracks its version via `bump2version`, configured in `.bumpversion.cfg`:**

```ini
[bumpversion]
current_version = 1.2.18
```

Every file that must stay in sync is listed there as a `[bumpversion:file:...]` section —
today that's `pyproject.toml`, `README.md`, and `.bmadrc.yaml`. Adding a new file to the
sync set means adding a section to `.bumpversion.cfg`, not writing a new sync script.

(A prior, separate mechanism — `.claude/scripts/version-bump.sh` / `version-sync.sh`, treating
`.bmadrc.yaml` as its own independent source of truth — was retired: it never actually ran in
practice, and its target `.ai/*.txt` path was migrated to `.bmad/local/*.txt` — the two
mechanisms had drifted out of sync with each other for a long time before being consolidated.)

### 🚀 Version Management Commands

**Bump is never run directly by the agent.** It is triggered by the `[patch candidate]` (or
appropriate) marker in the **user's own commit message** — the agent must never add that
marker on its own initiative, no matter how clear-cut the change seems.

**Preview only** (safe for the agent to run, changes nothing):

```bash
.venv/bin/bumpversion --dry-run --list --allow-dirty patch   # or minor / major
```

### ✅ What Happens on Version Bump

1. The user's commit carries the bump marker.
2. `bump2version` reads `current_version` from `.bumpversion.cfg`.
3. Validates the new version follows SemVer rules (rejects 0.x.x and 1.0.0 — same rule as
   above, enforced by convention/review here, not by a script-level guard).
4. Updates every file listed under a `[bumpversion:file:...]` section, and commits (per
   `commit = True` in the config).

### 🚫 NEVER Manually Edit Versions

- **NEVER** edit version fields in `pyproject.toml`, `README.md`, `.bmadrc.yaml`, or any other
  bumpversion-tracked file directly.
- **ALWAYS** let the `[patch candidate]`-triggered bump update them together.

### 🎯 Benefits

1. **Single Source of Truth**: `.bumpversion.cfg`'s `current_version` is THE version.
2. **Automatic Sync**: every tracked file updates together, never drifts.
3. **User-gated**: the marker lives in the user's own commit — no agent-run script to approve.
4. **Scalable**: adding a new file to keep in sync is one `.bumpversion.cfg` section.

---

---

**Version**: 1.0.2
**Last Updated**: 2025-10-31
**Status**: Production
**Enforcement**: MANDATORY
