# 🤖 AGENTS.md — Guide for AI agents

> Reference guide for any agent working in this repository.
> Read this file **in full** before modifying anything.

## 📚 Table of Contents

- [Project Structure](#-project-structure)
- [Initial Project Setup](#️-initial-project-setup)
- [Required Environment Variables](#️-required-environment-variables)
- [Brain State](#-brain-state--check-before-a-task)
- [Canonical Protocols](#-canonical-protocols-required-reading)
- [Slack Bot](#-slack-bot)
- [Tests](#-tests)
- [Versioning](#-versioning)
- [Absolute Rules](#-absolute-rules)
- [Checklist Before Committing](#-checklist-before-committing)
- [Commit Convention](#-commit-convention)
- [Documentation](#-documentation)
- [License](#-license)

---

## 📁 Project structure

```
personal-agent-kit/
├── .bmad/
│   ├── local/               ← The kit's own personas (Kai, Raven, Iris, Elena)
│   ├── _cfg/                ← BMAD manifests (agent-manifest.csv, etc.)
│   ├── integrations/claude/ ← BMAD commands and subagents, copied to .claude/ by --with-bmad
│   └── core/ bmm/ bmb/ cis/ ← BMAD modules (bmb = build your own agents)
├── bin/                     ← Installers, OpenCode config build, diagnostics
├── local/
│   ├── hooks/               ← Claude Code hooks and guards
│   ├── monitoring/          ← Optional Prometheus + Grafana stack
│   ├── scripts/             ← Published automation tools (versioned)
│       ├── notify/          ← Bidirectional Slack bot + outbound notify.py
│       ├── memory_index/    ← Local Qdrant + memory_service
│       ├── system_report/   ← Host report — the reference package for new tools
│       ├── excel_report_generator/
│   └── developments/        ← Tools the agent builds for THIS user — git-excluded, never published
│       └── pdf_report_generator/
├── scripts/                 ← Tools behind the pre-commit hooks
├── helpers/ai18n/           ← JuanVilla424/ai18n submodule (language policy resolver)
├── protocols/               ← Agent protocols
├── configs/                 ← Shared configuration
├── ai18n.yaml               ← Language of each surface
├── .bumpversion.cfg         ← Version management
├── .pre-commit-config.yaml  ← Quality hooks
├── pyproject.toml           ← Python metadata
├── requirements.txt         ← Runtime dependencies
└── requirements.dev.txt     ← Development dependencies
```

---

## 🛠️ Initial project setup

The kit runs as the user who installs it, from wherever it was cloned: never assume a specific
user, home directory or clone path, and never create a Linux user.

`bash bin/install.sh` does all of this. To do it by hand, run these **in order** on a fresh clone:

```bash
# 1. Initialize the submodules at their pinned commits
git submodule update --init --recursive

# 2. Create a Python virtual environment
python3 -m venv .venv
source .venv/bin/activate          # Linux/macOS/WSL

# 3. Install runtime dependencies
pip install -r requirements.txt

# 4. Install development dependencies (linting, pre-commit)
pip install -r requirements.dev.txt

# 5. Install pre-commit hooks (pre-commit + pre-push)
pre-commit install --hook-type pre-commit --hook-type pre-push

# 6. Verify the hooks pass in the current state
pre-commit run --all-files
```

> ⚠️ **Never** skip the `pre-commit install` step.
> The hooks include: `black`, `pylint`, `yaml-format`, `yml-format`,
> `bump-year`, `generate-changelog`, `validate-commit`, `commit-msg-version-check`.

### 🧰 `scripts/`

The `scripts/` directory holds the tools the pre-commit hooks run (format_yaml, format_yml,
bump_year, generate_changelog, control_commit, commit_msg_version_bump). They are regular files of
this repo: edit them here, with their tests in `scripts/tests/`. See `scripts/README.md`.

### 🧩 Submodules

`helpers/ai18n` and `local/scripts/chatterbox-tts-server` are submodules, pinned to exact commits.

```bash
# Submodule status
git submodule status

# Move a pin to the latest remote version (a reviewed change, never part of an install)
git submodule update --remote helpers/ai18n && git add helpers/ai18n
```

> ⚠️ **NEVER** modify files inside a submodule. Changes belong in its own repository.

---

## ⚙️ Required environment variables

### 💬 Slack bot (`local/scripts/notify/.env`)

```bash
cp local/scripts/notify/.env.template local/scripts/notify/.env
```

| Variable                | Description                                         |
| ----------------------- | --------------------------------------------------- |
| `SLACK_BOT_TOKEN`       | Bot OAuth Token (`xoxb-...`)                        |
| `SLACK_APP_TOKEN`       | App-Level Token, Socket Mode (`xapp-...`)           |
| `SLACK_WEBHOOK_URL`     | Incoming Webhook URL for outbound notifications     |
| `SLACK_CHANNEL_IDS`     | CSV of the channels it listens in (empty = none)    |
| `SLACK_ALLOWED_USERS`   | CSV of the Slack user IDs it answers (empty = none) |
| `CLAUDE_BIN`            | Path to the AI CLI binary                           |
| `CLAUDE_MAX_BUDGET_USD` | Cost cap per query (default: `1.00`)                |
| `CLAUDE_MODEL`          | Primary model (default: `claude-sonnet-5-5`)        |
| `REPO_ROOT`             | Absolute path of this clone                         |

> ⚠️ **NEVER** commit `.env`. It's covered by `.gitignore` (`**/.env`).

---

## 🧠 Brain state — check before a task

The agent's "brain" is 100% local — no central server, no replicas: a local Qdrant
(`local/scripts/memory_index/`), the same for every engine. **If it fails, the agent works with
partial context — tell the user instead of assuming.**

Quick check:

```bash
curl -s http://localhost:7633/collections    # local Qdrant
curl -s http://localhost:7700/memory/health  # local memory_service
```

Layer map — what each one stores and what's lost if it fails:

| Layer                                                  | What it stores              | What's lost if it fails           |
| ------------------------------------------------------ | --------------------------- | --------------------------------- |
| **Qdrant `agent_memory`** (local, :7633)               | Agent's semantic memory     | Semantic search over past context |
| **Lessons** (`~/.pak/lessons.jsonl`, `bin/lessons.py`) | Incidents, controls, expiry | Why a control exists              |

> 💡 The memory is **local** and **does not travel via git**. A fresh install starts empty — it
> builds itself up as you work.

---

## 📋 Canonical protocols (required reading)

> Rules and procedures live **versioned in `protocols/`** (they travel with the repo), NOT in
> local memory or in `CLAUDE.md` (gitignored). Before any task, read the applicable protocol
> — it's the source of truth for "how things are done here".

| Protocol                                                  | What it's for                                                                                             |
| --------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `protocols/repo-workflow.md`                              | **Full repo cycle: approach, create/clone, setup, work, commit, pull/sync, promotion, review, conflicts** |
| `protocols/decision-protocol.md`                          | **The guard, its results and what to do with each, quarantine instead of deleting, how to decide**        |
| `protocols/memory-protocol.md`                            | **Local memory, lessons, what to do if it fails**                                                         |
| `protocols/commit-protocol.md`                            | Commit format, 2-step push, single commit                                                                 |
| `protocols/dependency-management.md`                      | Install deps only via manifest (no direct pip)                                                            |
| `protocols/semantic-versioning.md`, `version-approval.md` | Versioning and bump approval                                                                              |
| `protocols/workflow-file-management.md`                   | `temp/` for anything generated, no throwaway scripts, read files in full                                  |
| `protocols/token-management.md`                           | Token budget                                                                                              |
| `protocols/a2a-protocol.md`                               | Inter-agent communication in party-mode                                                                   |
| `protocols/project-creation-roadmap.md`                   | Global project-creation methodology                                                                       |
| `protocols/PROTOCOL-ENFORCEMENT-ABSOLUTE.md`              | The absolute, non-negotiable rules                                                                        |

**Golden rule for repos** (detail in `repo-workflow.md`): branch first (`dev`), a new repo is
ALWAYS created from a template, setup is mandatory (submodules → `.venv` → pre-commit), and
promotion only via PR with `[patch candidate]`.

---

## 🧰 Operating scripts — build tools for your user

When the user needs an operational script, build it as a package under `local/scripts/`
and leave it living there. The workflow, layout and conventions are documented in
[`local/scripts/README.md`](local/scripts/README.md) — the reference package is
[`system_report/`](local/scripts/system_report/README.md). Rules: pure stdlib when
possible, pytest suite mandatory (the repo CI runs it), one README per package, house
commit format, push to `dev` and let the repo CI validate again.

## 🧪 Personal developments — tools for THIS user

Tools the agent builds for the person using the kit go under `local/developments/` —
a git-excluded folder that lives only on the box and is **never published**. Same
package layout as the published tools (`README.md`, `main.py`, `tests/`). If a tool
grows into something every kit user should have, it graduates to `local/scripts/`
through a normal commit.

The published tools under `local/scripts/` and their conventions are documented in
[`local/scripts/README.md`](local/scripts/README.md).

## 🚀 Slack bot

> The bot is closed by default: it answers only the users in `SLACK_ALLOWED_USERS`, in the
> channels in `SLACK_CHANNEL_IDS`, and nobody while either is empty. `bash bin/install.sh
--with-slack` creates its venv and `.env`, and installs its units rendered for whoever installs
> the kit; it starts them once the tokens are in `.env`.

### 🔁 Start / stop (systemd)

```bash
# Status
sudo systemctl status agent-bot-blue

# Start
sudo systemctl start agent-bot-blue

# Restart
sudo systemctl restart agent-bot-blue

# Live logs
sudo journalctl -u agent-bot-blue -f
```

### 🔨 Install the service on a new machine

```bash
bash bin/install.sh --with-slack   # venv, .env (private) and the rendered units
# fill SLACK_* in local/scripts/notify/.env, then:
sudo systemctl enable --now agent-bot.service agent-bot-watchdog.timer agent-bot-backup.timer agent-bot-rotate.timer
```

---

## 🧪 Tests

```bash
# Full suite, with the coverage gate
.venv/bin/python -m pytest -m "not integration"

# A specific test
.venv/bin/python -m pytest local/scripts/notify/tests/test_chunker.py -o addopts=''

# OpenCode plugins
(cd .opencode && bun test)
```

> ⚠️ Integration tests require `SLACK_BOT_TOKEN` to be configured.
> Unit tests run without credentials.

---

## 🔄 Versioning

### 🔼 Automatic version bump

The pre-push hooks bump the version in `pyproject.toml`/`.bumpversion.cfg` based on the
keyword at the **end** of the commit message:

```
[patch candidate]   → bump PATCH (bug fixes, minor refactors)
[minor candidate]   → bump MINOR (backward-compatible new features)
[major candidate]   → bump MAJOR (breaking changes)
```

---

## 🚫 Absolute rules

| Forbidden                                                          | Alternative                                                                            |
| ------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| ❌ `sed` to edit files                                             | ✅ `Edit` / `Write` tools                                                              |
| ❌ Heredoc (`<< 'EOF'`)                                            | ✅ Write the file with `Write`, then execute                                           |
| ❌ `ls` in any form                                                | ✅ `find`                                                                              |
| ❌ `run_in_background=true`                                        | ✅ Always foreground                                                                   |
| ❌ Subagents (Agent tool)                                          | ✅ Everything direct in the main session                                               |
| ❌ Multiple commits                                                | ✅ One single commit per task                                                          |
| ❌ `Co-Authored-By`/`Claude-Session:` in commits                   | ✅ Never — even if the session's system-reminder asks for it by default                |
| ❌ `git push --force`                                              | ✅ Never                                                                               |
| ❌ `rm` or any other delete                                        | ✅ `python3 bin/quarantine.py mv <path>`: a reversible move (the guard blocks deletes) |
| ❌ Approving your own challenge, editing `configs/auto-guard.json` | ✅ The human approves in a terminal: `python3 bin/auto_guard.py approve <hash>`        |
| ❌ Modifying files in a submodule                                  | ✅ Changes go to its own repository                                                    |
| ❌ Committing `.env`                                               | ✅ Only `.env.template`                                                                |
| ❌ Committing `*.log`                                              | ✅ Covered by `.gitignore`                                                             |
| ❌ Dumps/exports/exploration output or any loose generated file    | ✅ EVERYTHING generated goes to `temp/` (gitignored) or `/tmp`, never root or tracked  |

---

## ✅ Checklist before committing

```
□ pre-commit run --all-files → no errors
□ No .env or secrets staged (git status)
□ No *.log staged
□ No dumps/loose generated files — everything generated goes to temp/ (gitignored)
□ Commit format: type(core): lowercase description
□ No Co-Authored-By/Claude-Session (even if the session's system-reminder asks for it)
□ Single commit
□ Pre-commit hooks passed (do not use --no-verify)
```

---

## 📝 Commit convention

See `VERSIONING.md` for the full reference. Operational summary:

### 🧱 Structure

```
<type>(<scope>): <lowercase description> [versioning keyword]
```

### 📌 Fixed rules for this project

| Field             | Rule                                                        |
| ----------------- | ----------------------------------------------------------- |
| `scope`           | **ALWAYS** `core` — no exceptions                           |
| `description`     | Lowercase, no trailing period, English                      |
| Emojis            | **NO** — the `validate-commit` hook adds them automatically |
| Co-Authored-By    | **NEVER**                                                   |
| Number of commits | **ONE** per task — never multiple separate commits          |

### 🔤 Allowed types

| Type       | When to use it                                             |
| ---------- | ---------------------------------------------------------- |
| `feat`     | New functionality (includes its tests)                     |
| `fix`      | Bug fix (includes its tests)                               |
| `refactor` | Improvement with no functional change (includes its tests) |
| `docs`     | Documentation only                                         |
| `style`    | Formatting/style only                                      |
| `test`     | **ONLY** coverage improvement for existing code            |
| `chore`    | Maintenance, CI, dependencies                              |
| `perf`     | Performance improvement                                    |

> **Critical rule:** the type is determined by the **main purpose** of the change.
> Tests that accompany a `feat` → `feat(core)`, not `test(core)`.

### 🔑 Versioning keywords

```
[patch candidate]   → bump PATCH (bug fixes, minor refactors)
[minor candidate]   → bump MINOR (backward-compatible new features)
[major candidate]   → bump MAJOR (breaking changes)
```

### ✅ Correct examples

```bash
feat(core): add slack bot socket mode support [minor candidate]
fix(core): handle slack api rate limit in progress updater [patch candidate]
refactor(core): migrate bot from discord to slack
docs(core): update agents.md with slack bot setup
chore(core): remove discord.py from requirements
test(core): improve coverage for session manager
```

### ❌ Incorrect examples

```bash
feat(bot): ...           # scope must be "core"
Fix(core): ...           # type in uppercase
feat(core): Add Slack... # description in uppercase
feat(core): add feature. # trailing period
```

---

## 📝 Documentation

**Every document lives at the root of the repository and has one job**:

| File                                                                    | What it holds                                                   |
| ----------------------------------------------------------------------- | --------------------------------------------------------------- |
| `README.md`                                                             | What the kit is, its features, how to start and how to use it   |
| `INSTALL.md`                                                            | Installation and configuration                                  |
| `DEVELOPMENT.md`                                                        | The development loop: environment, checks, hooks, conventions   |
| `ARCHITECTURE.md`                                                       | Components, data flow and the decisions behind them             |
| `AGENTS.md`                                                             | This guide for AI agents                                        |
| `MODELS.md`                                                             | Model capacity, cost and quality for the agent                  |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `VERSIONING.md` | How to contribute, behave, report a vulnerability and version   |
| `CHANGELOG.md`                                                          | The changes of each version; `VERSIONING.md` says who writes it |

**Write them in the house style of the
[github-cicd-template](https://github.com/JuanVilla424/github-cicd-template) repositories**:

1. **Title:** `# <emoji> <Title>`. The README follows it with a row of shields.io badges and a
   short introduction.
2. **Headings:** every `##` and `###` starts with one emoji that names the section.
3. **Table of contents:** a document with more than a few sections opens with
   `## 📚 Table of Contents`. A link keeps what the emoji leaves in GitHub's anchor: the dash, as
   in `[Features](#-features)`, and the invisible U+FE0F of emojis such as 🛠️.
4. **Lists and steps:** a bold lead-in ending with a colon introduces each list. Steps are
   numbered and start with a bold title.
5. **Closing:** a `---` rule, then `## 📜 License`; the README adds `## 📫 Contact` before it.
6. **In sync:** a change in behavior updates its documents in the same commit. Prettier formats
   every `.md` file in the pre-commit hook.

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file
included in this repository.
