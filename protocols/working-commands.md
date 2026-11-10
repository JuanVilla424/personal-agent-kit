# Working Commands Protocol - BMAD

**Version**: 1.0.1
**Last Updated**: 2025-11-02
**Status**: Production
**Enforcement**: Reference (check before executing unfamiliar commands)

---

## 📋 Overview

This protocol documents **tested, working commands** for this system to prevent wasting time on commands that will fail.

**Purpose**:

- ✅ Avoid re-testing failed commands (like `tree`, macOS `stat`, etc.)
- ✅ Provide working alternatives for common tasks
- ✅ Document system-specific command syntax
- ✅ Save context by not repeating failed command attempts

**Protocol Compliance**:

- ✅ This is documentation/reference (not a script)
- ✅ Commands should still be executed via Bash tool
- ✅ Updated as new working commands are discovered

---

## 🖥️ System Information

**Detected System**: Linux (Ubuntu/Debian-based)
**Shell**: bash
**Python**: Available (`python3`)
**Node**: Available (`node`, `npm`)

---

## 📁 File System Commands

### Directory Listing

**✅ WORKS: `find` with depth control**

```bash
# List directories up to depth 3 (excluding src, venv, git)
find . -maxdepth 3 -type d ! -path "./src/*" ! -path "./.venv/*" ! -path "./.git/*" | sort

# List only files by pattern
find . -maxdepth 2 -type f -name "*.md" | sort

# List files in directory tree
find temp/ -type f | sort
```

**✅ WORKS: `ls` standard options**

```bash
# List with details and human-readable sizes
ls -lh

# List all including hidden files
ls -la

# List only directories
ls -d */
```

**✅ WORKS: `tree` (UPDATED 2025-11-02)**

```bash
# Tree view of directory structure
tree temp/

# Limit depth
tree -L 2 temp/

# Tested: 2025-11-02 - tree IS installed on this system
```

---

### File Statistics

**✅ WORKS: `stat` (Linux syntax)**

```bash
# Get file size (Linux)
stat -c%s filename

# Get modification time
stat -c%Y filename
```

**❌ DOES NOT WORK: `stat` (macOS syntax)**

```bash
# macOS syntax: stat -f%z filename
# This system uses Linux - use -c not -f
```

**✅ PORTABLE ALTERNATIVE**:

```bash
# Works on both Linux and macOS
wc -c < filename  # File size in bytes
ls -lh filename   # Human-readable size
```

---

### File Finding

**✅ WORKS: `find` with conditions**

```bash
# Find by name pattern
find . -name "*.md" -type f

# Find files modified in last N days
find temp/snapshots/ -name "*.md" -mtime +7

# Find executable scripts
find .claude/scripts -type f -name "*.sh" -executable

# Find and execute command on results
find .bmad/local/ -name "*.txt" -exec sed -i 's|old|new|g' {} \;
```

---

## 🔍 Content Search

**✅ WORKS: `grep` with regex**

```bash
# Case-insensitive search
grep -i "pattern" file.txt

# Recursive search (excluding directories)
grep -r "pattern" directory/ --exclude-dir=src --exclude-dir=.venv

# With line numbers
grep -n "pattern" file.txt

# Extended regex (|, +, ?, etc.)
grep -E "pattern1|pattern2" file.txt

# Word boundaries (exact word match)
grep -E '\bcontinue\b' file.txt

# Count matches
grep -c "pattern" file.txt

# List files with matches only
grep -l "pattern" *.txt
```

**✅ WORKS: `grep` with context**

```bash
# Show surrounding lines
grep -C 3 "pattern" file.txt  # 3 lines before and after
grep -A 2 "pattern" file.txt  # 2 lines after only
grep -B 2 "pattern" file.txt  # 2 lines before only
```

---

## 📝 Text Processing

**✅ WORKS: `sed` for replacements**

```bash
# In-place replacement (Linux)
sed -i 's|old|new|g' file.txt

# Preview without modifying
sed 's|old|new|g' file.txt

# Use | as delimiter (better for paths)
sed -i 's|/old/path|/new/path|g' file.txt

# Multiple files
find .bmad/local/ -name "*.txt" -exec sed -i 's|old|new|g' {} \;
```

**✅ WORKS: `awk` for field extraction**

```bash
# Extract specific field (space-delimited)
awk '{print $2}' file.txt

# Custom delimiter
awk -F':' '{print $1}' /etc/passwd

# Extract version from YAML
grep '^version:' .bmadrc.yaml | awk '{print $2}'

# Conditional printing
awk '$3 > 100' data.txt
```

**✅ WORKS: `cat` and related**

```bash
# Display file
cat file.txt

# With line numbers
cat -n file.txt

# Concatenate multiple files
cat file1.txt file2.txt > combined.txt

# Head/tail
head -n 20 file.txt
tail -n 20 file.txt
```

---

## 🔧 Script and Permission Commands

**✅ WORKS: `chmod` for permissions**

```bash
# Make script executable
chmod +x script.sh

# Check if file is executable
test -x script.sh && echo "Executable" || echo "Not executable"

# Alternative check
[[ -x script.sh ]] && echo "Executable"
```

**✅ WORKS: Script execution**

```bash
# Execute bash script
./script.sh

# Execute with bash explicitly
bash script.sh

# With arguments
./script.sh arg1 arg2 --flag

# Execute and capture output
OUTPUT=$(./script.sh)
```

---

## 📦 Command Availability

**✅ WORKS: Check if command exists**

```bash
# Best method (portable)
command -v tree >/dev/null 2>&1 && echo "Available" || echo "Not available"

# Alternative methods
which tree
type tree

# Use in conditionals
if command -v tree >/dev/null 2>&1; then
    tree temp/
else
    find temp/ -type d | sort
fi
```

**✅ WORKS: Version checks**

```bash
# Python
python3 --version

# Pip
pip3 --version

# Node
node --version

# npm
npm --version

# Git
git --version
```

---

## 🕐 Date and Time

**✅ WORKS: `date` formatting**

```bash
# Current date ISO format
date '+%Y-%m-%d'

# Current datetime
date '+%Y-%m-%d %H:%M:%S'

# ISO 8601 format
date '+%Y-%m-%dT%H:%M:%S%z'

# Unix timestamp
date +%s

# Format for filenames
date '+%Y%m%d-%H%M%S'  # 20251102-143045
```

---

## 📊 JSON/YAML Processing

**⚠️ MAY NOT WORK: `jq` (check first)**

```bash
# If jq is installed
cat file.json | jq '.key'

# Check if jq available
command -v jq >/dev/null 2>&1 && echo "Available"
```

**✅ WORKS: JSON without jq (alternative)**

```bash
# Extract simple key with grep
grep '"key"' file.json | awk -F'"' '{print $4}'

# Or with sed
grep '"version"' file.json | sed 's/.*: "\(.*\)".*/\1/'
```

**❌ DOES NOT WORK: `yq` (not installed)**

```bash
# yq for YAML - NOT available on this system
```

**✅ WORKS: YAML without yq (alternative)**

```bash
# Extract simple key from YAML
grep '^version:' .bmadrc.yaml | awk '{print $2}'

# Extract nested key
grep '  port:' config.yaml | awk '{print $2}'
```

---

## 🔍 Process and System

**✅ WORKS: Process information**

```bash
# List processes
ps aux | grep pattern

# Current working directory
pwd

# Environment variables
echo $PATH
echo $HOME
printenv | grep PATTERN
```

**✅ WORKS: Disk usage**

```bash
# Human-readable disk usage
du -h directory/

# Summary only
du -sh directory/

# Sort by size
du -h | sort -h

# Disk free space
df -h
```

---

## 🚫 Known Non-Working Commands

Document commands that have been tested and DON'T work:

1. **❌ `yq`** - Not installed (tested 2025-11-02)
   - **Use instead**: `grep` + `awk` for simple YAML

2. **❌ `stat -f`** - macOS syntax (this is Linux)
   - **Use instead**: `stat -c` (Linux syntax)

3. **❌ `jq`** - May not be installed (check first)
   - **Use instead**: `grep` + `awk` + `sed` combinations

---

## 📝 Usage Protocol

### When to Consult This Protocol

✅ **Check this file BEFORE executing**:

- Commands that might vary by OS (`stat`, `date`, `sed -i`)
- Commands that might not be installed (`tree`, `yq`, `jq`)
- Complex commands you're unsure about

### When to Update This Protocol

✅ **Add to this file when**:

- You discover a command works (especially after testing)
- You find the correct syntax for a tricky command
- You discover a working alternative to a failed command
- You test OS-specific variations

### Update Format

When adding new commands:

````markdown
**✅ WORKS: [Brief description]**

```bash
# Working command
command --options arguments
```
````

**Context**: When this is useful
**Tested**: YYYY-MM-DD

```

---

## 🔄 Quick Reference Table

| Task | Working Command | Alternative | Status |
|------|----------------|-------------|--------|
| Tree view | `tree temp/` | `find . -type d \| sort` | ✅ (Updated 2025-11-02) |
| File size | `stat -c%s file` | `wc -c < file` | ✅ |
| Search | `grep -r "pattern" dir/` | N/A | ✅ |
| Replace | `sed -i 's\|old\|new\|g' file` | N/A | ✅ |
| JSON parse | `grep + awk` | `jq` (check first) | ✅ |
| YAML parse | `grep + awk` | `yq` (not available) | ✅ |
| Date format | `date '+%Y-%m-%d'` | N/A | ✅ |
| Check cmd | `command -v cmd` | `which cmd` | ✅ |

---

## 🎯 Integration with Workflow

This protocol integrates with the **Workflow & File Management Protocol**:

- ✅ This is REFERENCE documentation (not a script)
- ✅ Commands still executed via Bash tool (transparent)
- ✅ Prevents wasted context on failed commands
- ✅ Improves efficiency without violating protocols

**Example workflow**:
1. Need to list directory tree
2. Check this protocol → `tree` doesn't work
3. Use working alternative: `find . -type d | sort`
4. Execute via Bash tool

---

**Remember**: This protocol saves time and context by documenting what works. Always execute commands transparently via Bash tool, never create automation scripts.

---

**Version**: 1.0.1
**Last Updated**: 2025-11-02 (tree availability verified)
**Maintained By**: BMAD Framework
**Status**: Production - Actively maintained based on testing
```
