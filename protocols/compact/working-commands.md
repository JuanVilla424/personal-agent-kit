# Working Commands Protocol (Compact)

**Version**: 1.0.1

## Core Rules

### System Commands

- OS: Linux (WSL2)
- Shell: bash
- User: <user>
- Python: `.venv/bin/python` (never system python3)
- Node: via nvm

### Critical Non-Working Commands

❌ `yq` - NOT installed (use manual YAML editing)
❌ `stat -c` (macOS syntax) - Use `stat --format` (Linux)
❌ `readlink -f` (non-standard) - Use `realpath`

### Mandatory Patterns

**File Operations:**

- Read: `cat`, `head -n`, `tail -n`
- Search: `grep -r`, `find`
- Edit: Use Edit tool (NEVER sed/awk in scripts)
- Write: Use Write tool (NEVER cat/echo/heredoc)

**Git Operations:**

- Status: `git status --short`
- Add: `git add <file>`
- Commit: `git commit -m "message"`
- NEVER: `git commit --amend` unless explicitly requested

**Package Management:**

- NPM: `npm install`, `npm run <script>`
- Global: `npm install -g <package>`
- NEVER: Direct installs (follow dependency-management protocol)

**Version Operations:**

- Bump: triggered by `[patch candidate]` in the **user's own commit** → `bump2version` via
  `.bumpversion.cfg` (never run directly by the agent; preview only with
  `.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]`)
- Validate: `.claude/scripts/validate-post-update.sh` (MANDATORY after Write/Edit)

**Hook Operations:**

- List: `ls -la .claude/hooks/`
- Check permissions: `ls -l .claude/hooks/<hook-name>`
- Make executable: `chmod +x .claude/hooks/<hook-name>`

### Quick Reference

**Validation (MANDATORY):**

```bash
.claude/scripts/validate-post-update.sh
```

**Version Bump (requires approval):**

```bash
.venv/bin/bumpversion --dry-run --list --allow-dirty patch  # bugs (preview only)
.venv/bin/bumpversion --dry-run --list --allow-dirty minor  # features (preview only)
.venv/bin/bumpversion --dry-run --list --allow-dirty major  # breaking (preview only)
```

**Git Workflow:**

```bash
git status --short
git add <files>
git commit -m "feat: description"
```

## Violations = Task Halt

Using prohibited commands or syntax causes immediate task halt.
