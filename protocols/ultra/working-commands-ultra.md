# ⌨️ Working Commands Protocol (Ultra)

**Version**: 1.0.2
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🖥️ Environment

| Item   | Value                                     |
| ------ | ----------------------------------------- |
| OS     | Linux (WSL2 / Ubuntu)                     |
| Shell  | bash                                      |
| User   | <user>                                    |
| Python | `.venv/bin/python` (never system python3) |
| Node   | via nvm (`~/.nvm/nvm.sh`)                 |

---

## 🚫 Prohibitions

| Command                        | Why                      | Use instead                  |
| ------------------------------ | ------------------------ | ---------------------------- |
| `stat -c`                      | BSD flag, fails on Linux | `stat --format`              |
| `readlink -f`                  | Not portable             | `realpath`                   |
| `ls`, `ls -la`                 | Hangs on EFS/large dirs  | `find <path> -maxdepth 1`    |
| `python3 script.py`            | Uses system Python       | `.venv/bin/python script.py` |
| `pip install` directly         | Breaks isolation         | Update `requirements.txt`    |
| Shell redirects `>` / heredocs | Untracked changes        | Write/Edit tools             |

---

## ✅ Rules

**File operations:**

| Operation  | Command                                               |
| ---------- | ----------------------------------------------------- |
| Read       | Read tool (or `cat`, `head`)                          |
| Search     | `grep`, `find`                                        |
| Edit/Write | Write/Edit tools — NEVER `sed`/`awk`/`cat >`/`echo >` |

**Git:**

```bash
git status --short
git add <specific-file>          # never -A without review
git commit -m "type(core): msg"  # never --amend unless requested
```

**Version bump (requires approval):**

```bash
.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]   # preview only, never a real bump by the agent
.claude/scripts/validate-post-update.sh   # mandatory after
```

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS
