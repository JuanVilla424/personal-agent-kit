# Dependency Management Protocol (Compact)

**Version**: 1.0.1

## Absolute Prohibition

**NEVER execute direct install commands:**

- ❌ `pip install <package>`
- ❌ `npm install <package>`
- ❌ `yarn add <package>`
- ❌ Any direct package installation

## Required Workflow

**ALWAYS use file-based dependency management:**

1. **Update dependency file:**
   - Python: Add to `requirements.txt`
   - Node: Add to `package.json`

2. **Get user authorization:**
   - Explain why needed
   - State compatibility checks done
   - Wait for approval

3. **User installs:**
   - User runs installation commands
   - User reports success/failure

## Compatibility Requirements

**Before requesting new dependency:**

- Check version compatibility
- Verify no conflicts with existing deps
- Confirm necessity

## Authorization Template

```
📦 **New Dependency Required**

Package: <name>
Version: <version>
Purpose: <why needed>
Compatibility: <checks done>

Please approve and run:
  pip install <package>==<version>
OR
  npm install <package>@<version>
```

## Violations = Task Halt

Direct dependency installation causes immediate task halt.
