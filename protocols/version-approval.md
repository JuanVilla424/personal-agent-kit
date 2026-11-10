# Version Approval Protocol - BMAD

**Version**: 1.0.1
**Last Updated**: 2025-11-02
**Status**: Production
**Enforcement**: MANDATORY

---

## 📋 Overview

This protocol ensures that version bumps are **ALWAYS approved by the user** before execution. No automated version changes without explicit user consent.

**Purpose**:

- ✅ User maintains control over version progression
- ✅ Prevents accidental version bumps
- ✅ Ensures changelog accuracy
- ✅ Follows semantic versioning with user oversight

---

## 🚫 PROHIBITED: Automatic Version Bumps

**NEVER bump version automatically**, even if changes clearly warrant it.

**❌ ABSOLUTELY FORBIDDEN**:

```bash
# Agent adds the bump-trigger marker to its own commit
git commit -m "feat(core): ... [patch candidate]"  # WRONG - agent decided, not the user

# Agent assumes version should change
sed -i 's/version = "1.2.18"/version = "1.3.0"/' pyproject.toml  # WRONG - manual override
```

---

## ✅ REQUIRED: User Approval Workflow

### Step 1: Detect Significant Changes

**When to consider version bump**:

- ✅ New features added (MINOR bump candidate)
- ✅ Bug fixes implemented (PATCH bump candidate)
- ✅ Breaking changes made (MAJOR bump candidate)
- ✅ Multiple changes accumulated over session

**Detection Indicators**:

- New files created in `.claude/scripts/`
- New protocols added to `protocols/`
- Significant features in CHANGELOG
- User explicitly requests features

---

### Step 2: Analyze Change Type

**Classify changes according to SemVer**:

**PATCH (X.X.1)**:

- Bug fixes
- Documentation updates
- Minor script improvements
- No new functionality

**MINOR (X.1.0)**:

- New features (backwards-compatible)
- New protocols
- New scripts or tools
- Significant enhancements

**MAJOR (1.0.0)**:

- Breaking changes
- API changes
- Major restructuring
- Incompatible modifications

---

### Step 3: Propose Version Bump to User

**Format for proposal**:

```markdown
🔢 **Version Bump Recommended**

**Current Version**: 1.0.1
**Recommended Version**: 1.1.0
**Type**: MINOR (New Features)

**Reason**:
This session implemented the following new features:

- Anti-versioning system (validate-no-versioning.sh)
- Working Commands Protocol (protocols/working-commands.md)
- Cleanup automation (cleanup-temp.sh)
- Temp structure documentation (docs/temp-structure.md)
- Enhanced script headers (3 scripts)

**Semantic Versioning Classification**:

- New backwards-compatible features ✅ MINOR bump
- No breaking changes ✅ Not MAJOR
- More than just bug fixes ✅ Not PATCH

**Recommendation**: Bump to 1.1.0

**Do you approve this version bump?**

- "Apruebo" / "Yes" / "Sí" → Proceed with bump
- "No" / "Espera" / "Wait" → Skip for now
- "Patch solo" → Use PATCH instead (1.0.2)
```

---

### Step 4: Execute Only If Approved

**Upon user approval**:

The real mechanism is `bump2version` via `.bumpversion.cfg` (tracks `pyproject.toml`,
`README.md`, `.bmadrc.yaml`, and any other file listed there), triggered by the `[patch
candidate]` marker in the **user's own commit message** — never added by the agent on its own
initiative. Once the user's commit carries that marker:

```bash
# User's commit already includes "[patch candidate]" — the bump runs from that marker,
# not from the agent invoking anything directly.
# The agent MAY preview what would change first:
.venv/bin/bumpversion --dry-run --list --allow-dirty minor
```

**If user declines**:

```bash
# User says "No" or "Espera"
# Skip version bump
# Continue working
# Can propose again later if more changes accumulate
```

---

## 📊 Version Bump Decision Matrix

| Changes Made       | Bump Type | Example Version | Requires Approval |
| ------------------ | --------- | --------------- | ----------------- |
| Bug fixes only     | PATCH     | 1.0.1 → 1.0.2   | ✅ Yes            |
| New features       | MINOR     | 1.0.1 → 1.1.0   | ✅ Yes            |
| Breaking changes   | MAJOR     | 1.0.1 → 2.0.0   | ✅ Yes            |
| Documentation only | Optional  | No bump         | ✅ Yes (ask user) |
| No changes         | None      | Stay same       | N/A               |

**Every version bump requires user approval - NO EXCEPTIONS**

---

## 🎯 When to Propose Version Bump

### Recommended Timing

**✅ Good Times to Propose**:

- End of major feature implementation
- After completing improvement proposal
- User asks "What's next?" or "Are we done?"
- Session about to end (context nearing limit)
- User explicitly asks about version

**❌ Bad Times to Propose**:

- Middle of active development
- User is focused on debugging
- Just started working
- Context is low (< 20k tokens used)

---

## 💡 Example Conversation Flow

**Agent**:

> I've completed implementing the anti-versioning system, Working Commands Protocol, and cleanup automation. These are new features that warrant a MINOR version bump from 1.0.1 to 1.1.0 according to our Semantic Versioning Protocol.
>
> **Do you want me to bump the version to 1.1.0 now?**

**User Responses**:

**Scenario A - Approval**:

> "Yes, I approve"

**Agent**:

> ✅ Understood — go ahead and include `[patch candidate]` in your next commit and the bump
> will run automatically against `.bumpversion.cfg` (syncs `pyproject.toml`, `README.md`,
> `.bmadrc.yaml`, and any other tracked file).

---

**Scenario B - Decline**:

> "No, wait"

**Agent**:

> Understood, keeping version at 1.0.1 for now. I can propose the bump again later when you're ready.

---

**Scenario C - Alternative**:

> "Better use patch, 1.0.2"

**Agent**:

> Understood, using PATCH instead of MINOR. Include `[patch candidate]` in your commit and it
> bumps to 1.0.2 automatically.

---

## 🔒 Enforcement Rules

### For Agents

**MUST**:

- ✅ Always detect significant changes
- ✅ Always classify changes by SemVer rules
- ✅ Always propose version bump with clear reasoning
- ✅ Always wait for explicit user approval
- ✅ Always update CHANGELOG when bumping

**MUST NOT**:

- ❌ Never bump version without asking
- ❌ Never assume user wants version bump
- ❌ Never add the `[patch candidate]` commit marker on your own initiative
- ❌ Never modify `pyproject.toml`/`.bmadrc.yaml`/`README.md` version fields directly (that's
  what `.bumpversion.cfg` + the marker are for)

---

### For Users

**Control**:

- ✅ Full control over when versions bump
- ✅ Can approve, decline, or modify bump type
- ✅ Can request version bump anytime
- ✅ Can delay bump to later session

**Responsibility**:

- Keep in mind project versioning
- Approve bumps when appropriate
- Ensure CHANGELOG reflects changes

---

## 🔧 Integration with the Real Bump Mechanism

### Workflow

```bash
# Agent implements features
# Agent detects: "Multiple new features added"
# Agent proposes: "Recommend version bump to 1.1.0"
# Agent waits: User approval
# User approves and puts "[patch candidate]" (or the appropriate marker) in their own commit
# The bump itself runs from that marker via .bumpversion.cfg — the agent never invokes it
```

The single source of truth is `.bumpversion.cfg`'s `current_version` (mirrored in
`pyproject.toml`) — it lists every file that gets updated together (`pyproject.toml`,
`README.md`, `.bmadrc.yaml`, and any future addition). Adding a new tracked file means
adding a `[bumpversion:file:...]` section there, nothing else.

---

## 📝 Checklist for Version Bump

Before proposing version bump to user:

✅ **Changes Detected**: Clear list of what changed
✅ **Type Classified**: PATCH / MINOR / MAJOR determined
✅ **Reason Documented**: Why this bump type
✅ **User Available**: User is engaged and can respond
✅ **Timing Appropriate**: Not in middle of active work

After user approval:

✅ **Bump Executed**: user's commit carried the marker and `bump2version` ran successfully
✅ **Files Synced**: All agent files updated
✅ **CHANGELOG Updated**: Changes reflected in changelog
✅ **User Confirmed**: User sees confirmation message

---

## 🚀 Future Enhancement

**Potential Addition** (not yet implemented):

- Context7 integration for change detection
- Automated change classification
- Smart bump recommendations based on commit history
- Version bump reminders if many changes accumulate

---

## 📖 Related Protocols

- **[Semantic Versioning Protocol](semantic-versioning.md)** - Version number rules
- **[Workflow & File Management](workflow-file-management.md)** - General workflow rules

---

**Remember**: Users have final say on versioning. Always ask, never assume. Transparency and control are paramount.

---

**Version**: 1.0.1
**Last Updated**: 2025-11-02
**Maintained By**: BMAD Framework
**Status**: Production
**Enforcement**: MANDATORY
