## 🔧 WORKFLOW & FILE MANAGEMENT PROTOCOL - MANDATORY & ENFORCED

**CRITICAL: This protocol is ABSOLUTE and NON-NEGOTIABLE. Violations will cause IMMEDIATE HALT.**

### 📁 TEMPORARY DIRECTORY PROTOCOL

**Default temporary directory: `temp/` (local path in project root)**

**ABSOLUTE RULES:**

1. **✅ REQUIRED: All temporary/auxiliary files MUST go in `temp/`**

   ```bash
   # ✅ CORRECT - All temporary files in temp/
   temp/user-messages-history.md
   temp/protocols-block.md
   temp/verification-results.txt
   temp/add-protocols.sh

   # ❌ FORBIDDEN - Temporary files in root or other directories
   /debug-output.txt                # WRONG
   /scripts/helper.sh               # WRONG
   /analysis-results.md             # WRONG
   ```

2. **✅ REQUIRED: User messages history tracking**
   - **File**: `temp/user-messages-history.md`
   - **Update**: After EVERY user message
   - **Format**: Chronological log with translations, actions taken, and pending tasks
   - **Purpose**: Maintain complete conversation context and decisions

3. **🚫 PROHIBITED: Additional files outside temp/**

   ```bash
   # ❌ NEVER create files in these locations
   /root-level-file.txt             # FORBIDDEN
   /docs/generated-doc.md           # FORBIDDEN (unless explicitly requested)
   /scripts/automation.sh           # FORBIDDEN
   /utils/helper.py                 # FORBIDDEN

   # ✅ ONLY these locations are allowed
   temp/any-auxiliary-file.txt      # CORRECT
   ```

4. **✅ REQUIRED: `.gitignore` management**
   - Verify `temp/` is in `.gitignore`
   - Even if no git repository exists in current directory
   - Prevents accidental commits of temporary files

---

### 🚫 NO SCRIPTS POLICY - MANDATORY

**CRITICAL: NEVER create scripts to "speed things up" or "take shortcuts"**

**❌ ABSOLUTELY FORBIDDEN:**

```bash
# ❌ Creating automation scripts
temp/add-protocols.sh
temp/update-all-agents.sh
temp/verify-installation.py
temp/batch-process.sh

# ❌ Creating helper scripts
scripts/quick-fix.sh
scripts/mass-update.py
```

**✅ MANDATORY APPROACH:**

Instead of scripts, ALWAYS:

1. **Use direct tool calls** (Edit, Write, Bash with explicit commands)
2. **Spend context on explicit operations**
3. **Make each change visible and traceable**
4. **Never hide complexity behind scripts**

**Why this matters:**

- Scripts hide what's actually happening
- Context usage is TRANSPARENT and AUDITABLE
- Direct operations are SAFER and more CONTROLLABLE
- User can see EXACTLY what changes are being made

**Example - WRONG vs RIGHT:**

```bash
# ❌ WRONG - Creating script to update agents
#!/bin/bash
for agent in analyst pm po qa sm; do
  sed -i '/START:/i PROTOCOL_BLOCK' "$agent.txt"
done

# ✅ RIGHT - Direct Edit tool calls
Edit(file_path="<repo>/.bmad/local/database.txt", ...)
Edit(file_path="<repo>/.bmad/local/reports.txt", ...)
Edit(file_path="<repo>/.bmad/local/infra.txt", ...)
# Each operation visible, traceable, and safe
```

---

### 📖 FILE READING PROTOCOL - MANDATORY

**CRITICAL: ALWAYS read COMPLETE files. NEVER read partial/fragmented files.**

**🚫 PROHIBITED: Partial file reads**

```python
# ❌ FORBIDDEN - Reading file fragments
Read(file_path="config.py", offset=100, limit=50)  # WRONG - missing context
Read(file_path="agent.txt", limit=200)             # WRONG - incomplete view

# Why this is dangerous:
# - You might miss critical information outside the fragment
# - Context is lost between fragments
# - Multiple reads waste MORE tokens than one complete read
# - Risk of incorrect assumptions based on incomplete data
```

**✅ MANDATORY: Complete file reads**

```python
# ✅ CORRECT - Read entire file
Read(file_path="config.py")                        # RIGHT - complete context
Read(file_path="agent.txt")                        # RIGHT - full understanding

# Benefits:
# - Complete context in one operation
# - No missed information
# - More efficient overall (one read vs multiple partial reads)
# - Accurate understanding of file structure
```

**Exception handling:**

If file is genuinely too large (>10,000 lines):

1. ✅ Ask user if specific section is needed
2. ✅ Use grep/search to locate relevant sections first
3. ✅ Then read complete relevant sections (not arbitrary offsets)

**Example workflow:**

```bash
# If file is huge, locate first
Grep(pattern="class UserManager", path="large_file.py")
# Returns: "Found at line 2847"

# Then read surrounding context (complete logical section)
Read(file_path="large_file.py", offset=2800, limit=200)
# Read complete class definition, not arbitrary fragment
```

---

### 📝 README.md SYNCHRONIZATION PROTOCOL

**CRITICAL: README.md MUST reflect current project reality**

**Purpose**:

- **Primary audience**: AI agents working on the project
- **Secondary audience**: Human developers
- **Goal**: Provide accurate, up-to-date project state

**✅ REQUIRED: README.md must include**

1. **Current project structure**

   ```markdown
   ## Project Structure
   ```

   personal-agent-kit/
   ├── .bmad/local/ # Custom agent definitions
   │ ├── infra.txt
   │ ├── cybersecurity.txt
   │ └── ...
   ├── temp/ # Temporary files (gitignored)
   └── local/scripts/ # Automation (notify bot, report generators, memory_index)

   ```

   ```

2. **Active protocols**

   ```markdown
   ## Active Protocols

   All agents enforce:

   - 📦 Dependency Management Protocol (file-based only)
   - 🔢 Semantic Versioning Protocol (1.0.1 start mandatory)
   - 🔧 Workflow & File Management Protocol
   ```

3. **Version information**

   ```markdown
   ## Current Version

   - Project: 1.0.1
   - Last Updated: 2025-10-30
   - Protocols Version: 1.0.0
   ```

4. **Important paths and conventions**

   ```markdown
   ## Conventions

   - Temporary files: `temp/` (gitignored)
   - Agent definitions: `.bmad/local/*.txt`
   - Protocols: `protocols/`
   - User message history: `temp/user-messages-history.md`
   ```

**⚠️ Update triggers:**

README.md MUST be updated when:

- New protocols are added
- Project structure changes
- New agents are created
- Important conventions are established
- Version changes occur

**Note**: This is primarily for agents to understand project state, not for manual user maintenance.

---

### ✅ WORKFLOW PROTOCOL CHECKLIST

Before marking any task as complete:

✅ **Temporary Files**: All auxiliary files created in `temp/` only
✅ **User History**: `temp/user-messages-history.md` updated with latest message
✅ **No Scripts**: No automation scripts created (direct operations only)
✅ **Complete Reads**: All file reads are complete (no fragmented reads)
✅ **README Current**: README.md reflects current project state
✅ **Gitignore Valid**: `temp/` is in `.gitignore`
✅ **Context Transparent**: All operations visible and traceable

---

### 🎯 WORKFLOW ANTI-PATTERNS - AVOID THESE

❌ **Creating scripts for "efficiency"**

- Scripts hide complexity
- Use direct tool calls instead

❌ **Reading file fragments to "save tokens"**

- Fragments waste MORE tokens with multiple reads
- Missing context causes errors
- Read complete files once

❌ **Creating files outside temp/**

- Pollutes project structure
- Violates organization protocol
- Use temp/ for ALL auxiliary files

❌ **Outdated README.md**

- Agents get confused about project state
- Decisions based on wrong information
- Keep README current with reality

❌ **Skipping user history updates**

- Lost conversation context
- Cannot trace decision history
- Update after EVERY user message

**Remember: These workflow protocols ensure TRANSPARENCY, TRACEABILITY, and MAINTAINABILITY. Every operation must be visible, every file must be in the right place, and every read must be complete. No shortcuts, no scripts, no hidden complexity.**

---

---

**Version**: 1.0.1
**Last Updated**: 2025-10-30
**Status**: Production
**Enforcement**: MANDATORY
