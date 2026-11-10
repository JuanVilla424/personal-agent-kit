# Workflow & File Management Protocol (Compact)

**Version**: 1.0.1

## Absolute Rules

### 1. Temp Directory

**ALL temporary files MUST go in `temp/`**

- No exceptions
- No temp files in root or other directories

### 2. File Operations

**NEVER use bash for file writes:**

- ❌ `cat >`, `cat >>`
- ❌ `echo >`, `echo >>`
- ❌ Heredocs (`<< EOF`)

**ALWAYS use tools:**

- ✅ Write tool (for new files)
- ✅ Edit tool (for modifications)

### 3. Script Prohibition

**NEVER create scripts for automation**

- Use direct tool calls instead
- Scripts for build/deployment only

### 4. File Reading

**ALWAYS read complete files**

- Never partial/fragmented reads
- Use Read tool with full file content

### 5. Required Updates

**After every user message:**

```
temp/user-messages-history.md
```

**After significant changes:**

```
README.md (keep synchronized with reality)
```

### 6. Anti-Versioning

**NEVER create versioned filenames:**

- ❌ `file-v1.md`, `file-v2.md`
- ❌ `script_old.sh`, `script_new.sh`
- ✅ Use git for version control

### 7. Validation

**MANDATORY after Write/Edit:**

```bash
.claude/scripts/validate-post-update.sh
```

Fix ALL errors before proceeding.

## Violations = Task Halt

Breaking file management rules causes immediate task halt.
