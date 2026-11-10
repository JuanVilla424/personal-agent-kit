## 📦 DEPENDENCY MANAGEMENT PROTOCOL - MANDATORY & ENFORCED

**CRITICAL: This protocol is ABSOLUTE and NON-NEGOTIABLE. Violations will cause IMMEDIATE HALT.**

### 🚫 PROHIBITED: Direct Package Installation

**NEVER execute direct installation commands:**

```bash
# ❌ ABSOLUTELY FORBIDDEN - Will cause IMMEDIATE HALT
pip install <package>
pip install requests
npm install <package>
npm install axios
npm i express

# ❌ NEVER bypass the manifest files
pip install pandas==2.0.0  # Even with version specified - FORBIDDEN
npm install --save lodash  # Even with --save - FORBIDDEN
```

### ✅ MANDATORY: File-Based Dependency Management

**ALL dependency changes MUST follow this exact workflow:**

**Step 1: Verify & Research**

```bash
# Before adding ANY dependency:
# 1. Check latest stable version
# 2. Review release notes and breaking changes
# 3. Verify compatibility with existing dependencies
# 4. Check for known security vulnerabilities
# 5. Review package maintenance status and community support
```

**Step 2: Update Manifest File**

```bash
# Python projects - ONLY update requirements.txt
echo "requests==2.31.0  # HTTP library for API calls" >> requirements.txt
echo "pandas==2.0.3     # Data manipulation and analysis" >> requirements.txt

# Node projects - ONLY update package.json manually or via controlled command
# Manually edit package.json to add:
{
  "dependencies": {
    "express": "4.18.2",  // Web framework
    "axios": "1.5.0"      // HTTP client
  }
}
```

**Step 3: Test Compatibility (MANDATORY)**

```bash
# Create test environment first
python -m venv test_env
source test_env/bin/activate

# Test installation with new dependencies
pip install -r requirements.txt

# OR for Node:
npm install  # Install from package.json

# Run existing tests to verify compatibility
npm test
# OR
pytest
```

**Step 4: Install in Project (Only After Testing)**

```bash
# Python - ONLY allowed installation method
pip install -r requirements.txt

# Node - ONLY allowed installation method
npm install
# OR for clean install
npm ci
```

### 🔒 Authorization Requirements for Dependencies

**Adding new dependencies requires USER AUTHORIZATION with:**

```
🚨 USER AUTHORIZATION REQUIRED - DEPENDENCY ADDITION 🚨

DEPENDENCY NAME: [package-name]
VERSION: [specific version, e.g., 2.31.0]
PURPOSE: [Why this dependency is needed]

COMPATIBILITY TESTING:
✅ Latest stable version: [version]
✅ Compatible with [existing-package-1]: [status]
✅ Compatible with [existing-package-2]: [status]
✅ No known security vulnerabilities: [confirmed]
✅ Active maintenance: [last update date]
✅ License compatible: [license type]

ALTERNATIVES CONSIDERED:
- [Alternative 1]: [why not chosen]
- [Alternative 2]: [why not chosen]

FILE TO UPDATE:
- [✓] requirements.txt (Python)
- [ ] package.json (Node)

INSTALLATION COMMAND (will execute after approval):
- pip install -r requirements.txt
# OR
- npm install

🛑 WAITING FOR USER APPROVAL TO PROCEED 🛑
```

### 📋 Dependency Management Checklist

Before marking ANY task complete that involves dependencies:

✅ **Compatibility Verified**: All new dependencies tested with existing ones
✅ **Version Pinned**: Exact version specified (e.g., `==2.31.0` or `"4.18.2"`)
✅ **Security Checked**: No known vulnerabilities in chosen version
✅ **License Verified**: Compatible with project license
✅ **Documentation Updated**: CHANGELOG and requirements documented
✅ **Tests Passing**: All tests pass with new dependencies
✅ **User Approved**: Explicit authorization obtained

---

---

**Version**: 1.0.1
**Last Updated**: 2025-10-30
**Status**: Production
**Enforcement**: MANDATORY
