# 🧱 Architecture

How the **Personal Agent Kit** is built: its layers and components, how they connect, and the
decisions behind them.

> **Status**: Active | **Version**: 1.0.1 | **Date**: 2026-11-07

## 📚 Table of Contents

- [System Overview](#-system-overview)
- [Tech Stack](#-tech-stack)
- [Components](#-components)
- [How the Parts Connect](#-how-the-parts-connect)
- [Architecture Decisions](#-architecture-decisions)
- [Security Considerations](#-security-considerations)
- [Testing](#-testing)
- [License](#-license)

## 🔭 System Overview

PAK is a layer between the user and their coding agents. The engines run the agent loop. PAK adds
guards, memory, protocols and personas, and connects to each engine through the mechanisms the
engine already offers.

```
Engines       Claude Code · OpenCode
                   │ hooks/plugins · MCP · SKILL.md
Governance    write guard · rm guard · post-write judge
Memory        memory_service (local Qdrant) · MCP server · session hooks
Knowledge     protocols · personas · skills · ai18n.yaml
Optional      BMAD · voice (TTS) · monitoring · Slack bot · report generators
```

Everything runs on the user's machine, under the user's account. There is no central server, and
the kit creates no Linux user.

## 🧰 Tech Stack

### 🐍 Runtime

- **Language**: Python 3.11+ for services and hooks, Bash for installers and guards, JavaScript
  (Bun) for OpenCode plugins.
- **Memory**: Qdrant `v1.18.2` in Docker, bound to `127.0.0.1:7633`, and a FastAPI service on
  `:7700`. Embeddings run locally with fastembed.
- **Engines**: Claude Code and OpenCode.

### 🏭 Infrastructure

- **Services**: systemd units for `memory_service` and, when installed, `opencode-server`.
- **CI/CD**: GitHub Actions in `.github/workflows/ci.yml`.
- **Monitoring**: optional Prometheus, Pushgateway and Grafana stack in `local/monitoring/`.

## 🧩 Components

| Component         | Path                                                                      | Role                                      |
| ----------------- | ------------------------------------------------------------------------- | ----------------------------------------- |
| Installers        | `bin/install.sh`, `bin/_lib.sh`                                           | Set up the kit for the current user       |
| Commit tooling    | `scripts/`                                                                | Tools behind the pre-commit hooks         |
| Claude Code hooks | `local/hooks/`, `.claude/hooks/`                                          | Guards, session start, voice              |
| OpenCode plugins  | `.opencode/plugins/`                                                      | The same guards and session events        |
| OpenCode config   | `bin/opencode/`                                                           | Builds `~/.config/opencode/opencode.json` |
| Memory service    | `local/scripts/memory_index/`                                             | Single writer and search endpoint         |
| Memory MCP        | `bin/opencode/mcp_memory_server.py`                                       | Memory tools for both engines             |
| Guard             | `bin/auto_guard.py`, `bin/url_guard.py`                                   | One rule set for both engines             |
| Shell parser      | `bin/shell_parse.py`                                                      | Reads a command as bash would run it      |
| Snapshots         | `bin/snapshot.py`                                                         | Copies of a work tree, kept outside it    |
| Worker            | `bin/pak_worker.py`, `bin/worker/Dockerfile`, `bin/egress.py`             | Tasks in a container, reviewed patches    |
| Decision MCP      | `bin/decision_mcp.py`, `bin/decision.py`                                  | `guard_mutation`, optional engine         |
| Quarantine        | `bin/quarantine.py`                                                       | The only way to remove a file             |
| Injection scan    | `local/scripts/notify/security/injection_guard.py`, `bin/scan_context.py` | Memories and instruction files            |
| Protocols         | `protocols/`                                                              | Rules in three densities                  |
| Personas          | `.bmad/local/`                                                            | Kai, Raven, Iris and Elena                |
| BMAD              | `.bmad/`                                                                  | Optional team and agent builder           |
| Model map         | `configs/model-protocol-map.yaml`                                         | Model IDs by role, protocol variant       |
| Languages         | `ai18n.yaml`, `helpers/ai18n/`                                            | Language of each surface                  |
| Evals             | `evals/`                                                                  | Behavior checks against a real model      |

## 🔄 How the Parts Connect

### 🚪 Session Start

Claude Code runs `.claude/hooks/session-start.sh`, which cleans old files from `temp/` and prints
the orientation and the normalized language policy. It also scans the instruction files of the
session's directory (`AGENTS.md`, `CLAUDE.md`…) and warns about any that carry injection signals.
It prints the memory brief too: the most important memories, once, so the prompt stays cacheable.
In the background it takes a snapshot of the session's repository (`bin/snapshot.py`).
OpenCode gets the orientation, the policy and the memory brief through `instructions`, which
`build-config.sh` assembles and the session plugin refreshes at each start; the same plugin takes
the snapshot. It has no start hook that reaches the model, so it gets no scan warning.

### 🐚 A Command

1. The engine is about to run a shell command.
2. `auto-guard` matches it against the rules: a Claude Code hook, or an OpenCode plugin that calls
   the same Python CLI. Each rule reads the text and the command as bash would run it, with quotes,
   variables, wrappers and nested code resolved (`bin/shell_parse.py`). Block, challenge (ask the
   human) or allow.
3. A challenge first snapshots the session's repository in the background.
4. A guard that cannot judge blocks the command.

Both engines load the guards globally: `install-hooks.py` writes them to `~/.claude/settings.json`,
and `build-config.sh` lists the plugins in `~/.config/opencode/opencode.json`.

### 📝 A Write

1. The engine asks to write a file.
2. `pre-write-guard` blocks hardcoded secrets, credential files and broken syntax.
3. The file is written.
4. `post-write-judge` reviews it against `AGENTS.md` and reports findings. It never blocks.

### 🧠 A Memory

1. The agent calls `memory_add` or `memory_search` through MCP.
2. The MCP server forwards the call to `memory_service` with the token from `.env`.
3. On a write, `memory_service` scans the text: injection signals are refused, a warning is stored
   with its flags.
4. `memory_service` embeds the text and reads or writes Qdrant.

`memory_service` is the only writer. It refuses to start without authentication.

### 🐳 A Task

1. `pak task add` queues it; `pak task run` clones the repository into the task's folder.
2. Claude Code runs in a container (`bin/worker/Dockerfile`) with `--network none`, a read-only
   root, no capabilities, and only the clone, the task's HOME and the kit's guards mounted. Its one
   way out is a unix socket to a proxy on the host (`bin/egress.py`) that allows the model API, the
   base URL's host and `PAK_WORKER_EGRESS`, and records every request.
3. The change becomes a patch. A second call with no tools, in an empty folder, reviews it.
4. The human applies an approved patch, or not. Nothing is committed.

`--isolation host` runs the engine on the host instead, and must be asked for.

### 🔨 Installation

`bin/install.sh` settles its options from flags and prompts, and prints the plan before changing
anything. Then it installs the core tools, Claude Code, the submodules, `.venv` and `.env`,
registers the hooks and starts the brain. Templates carry `<user>` placeholders, and
`render_placeholders` fills them for the current user and clone path.

## 📏 Architecture Decisions

### 📌 Decision 1: a layer, not a runtime

**Context**: Harness quality decides a large part of an agent's results, and full runtimes are
expensive to build and keep up with.
**Decision**: Build on top of existing engines through hooks, MCP and SKILL.md.
**Consequences**: PAK cannot control what an engine does not expose. It can follow new engines
cheaply.

### 📌 Decision 2: the invoking user, any path

**Context**: Depending on a dedicated Linux user or a fixed path makes a kit hard to adopt.
**Decision**: The kit runs as whoever installs it, from wherever it was cloned. It never creates a
user, and templates are rendered at install time.
**Consequences**: Tests render every installed template for an arbitrary user and path.

### 📌 Decision 3: BMAD is optional

**Context**: BMAD is more than half of the files, and many users will not need it.
**Decision**: `.bmad/` ships with the repo. Its Claude Code commands and subagents live in
`.bmad/integrations/claude/` and are copied into `.claude/` only with `--with-bmad`.
**Consequences**: A default install has four personas and no BMAD commands. Activation is one flag.

### 📌 Decision 4: no downloaded scripts in the core install

**Context**: The guards forbid piping a download into a shell, so the core installer should not do
it either.
**Decision**: Docker and Node come from signed apt repositories. The optional development tools
still use their official installers.
**Consequences**: The core install is limited to systems with `apt`.

### 📌 Decision 5: the commit tooling lives in the repo

**Context**: The hooks only need 6 of the tools in a shared repository, and the kit must not inherit
what that repository carries.
**Decision**: `scripts/` holds those tools as regular files, with their tests.
**Consequences**: Fixes to the shared tools no longer arrive on their own; they are copied by hand.

### 📌 Decision 6: submodules stay pinned

**Context**: Moving to the upstream head during an install makes the result change from day to day.
**Decision**: The installer uses the recorded commits. Updating a pin is a reviewed change.
**Consequences**: Upstream fixes need an explicit bump.

### 📌 Decision 7: the worker's network is cut by the kernel

**Context**: A rule that reads command text cannot see what a script written to disk does, and an
autonomous task has nobody to answer a challenge.
**Decision**: `pak task` runs its engine in a container with `--network none`. A proxy outside the
container lets through only listed destinations, so a task can reach its model and nothing else.
**Consequences**: Tasks need Docker and an API key or a subscription token, since the human's login
on the host stays out. A task that needs a package index must list it in `PAK_WORKER_EGRESS`.

## 🔐 Security Considerations

- Services bind to `127.0.0.1` and `memory_service` requires a token.
- `.env` is created with mode 600 and is never committed.
- Guards are local and do not need a network or a model. Stage 2 is optional and off without
  `OPENROUTER_API_KEY`.
- A guard that cannot judge blocks. The plugins trust the guard next to their own file, never one
  in the session's directory.
- An agent cannot approve its own challenge: `approve` needs a terminal, and the rules block any
  command that runs it or touches the guard's settings.
- The Slack bot is closed by default: listed users in listed channels, nobody otherwise.
- `bin/skills-seed/` and `plugin/` hold third-party text. Treat updates to them as code.
- An autonomous task runs in a container with no network but its proxy, a read-only root and no
  capabilities. It never sees the kit's `.env`, the human's HOME or the real repository.
- Every session and every challenge first copies the repository to `~/.pak/snapshots`, outside it.
  `pak snapshot restore` writes a copy back and deletes nothing.

**Known limits:**

- The rules see what bash would run, but not what a script on disk does, and a program name
  built at run time is only challenged. On commands written for neither guard they stop 57 of 91
  harmful ones (`docs/guard-benchmark.md`). In an interactive session the snapshots are the line
  behind them; an autonomous task also has its container.
- OpenCode gets no warning about injected instruction files at session start.
- A redirect is not seen by the URL guard.

## 🧪 Testing

- `pytest -m "not integration"` runs the Python suite and enforces 96 % coverage.
- `bun test` in `.opencode/` runs the plugin tests.
- `bin/tests/test_installers.py` covers the options and the steps that need no network or root.
- `evals/datasets/guard-corpus.jsonl` and `url-guard-corpus.jsonl` run through Claude Code's
  hooks and OpenCode's plugins on every test run.
- `bin/tests/guard-e2e/run.sh` runs the real Claude Code and OpenCode against a scripted model:
  the guards block in each engine, with no key and no spend.
- `bin/tests/guard-e2e/worker.sh` runs a task in the real container against a scripted model:
  the guard blocks inside, the proxy refuses what is not listed, the cost cap stops a task, and a
  snapshot brings back a deleted file.
- `evals/guard_benchmark.py` scores the guard on a held-out set frozen by its sha256
  (`docs/guard-benchmark.md`); a test fails if the result drops below the recorded floor.
- `docs/install-test.md` records the full install in a clean container.
- `evals/` runs behavior checks against a real model, so it costs API credits.

[DEVELOPMENT.md](DEVELOPMENT.md#-quality-gates) says when to run each check.

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file
included in this repository.
