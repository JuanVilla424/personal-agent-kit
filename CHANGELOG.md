## [Unreleased]

### Features

- **core**: `bin/install.sh` runs without prompts (`--yes`), prints its plan (`--dry-run`) and takes
  flags for each optional part.
- **core**: BMAD is optional: its commands and subagents activate with `--with-bmad`.
- **core**: `ai18n.yaml` declares the language of each surface, with `--language` for replies and
  voice.
- **core**: GitHub Actions workflow for tests, plugin tests and pre-commit.
- **core**: one guard for both engines (`bin/auto_guard.py`): every shell command is judged before
  it runs, by a Claude Code hook and an OpenCode plugin that call the same rules. Challenges ask the
  human, a block is never approved, and a guard that cannot judge blocks.
- **core**: `bin/url_guard.py` stops fetches to loopback, private and metadata addresses, and
  secrets inside URLs and search queries, in both engines.
- **core**: `bin/quarantine.py` is the only way to remove a file: a reversible move with a checked
  sha256 manifest under `~/.pak/quarantine`.
- **core**: optional Stage 2 decision engine (`bin/decision.py`) and the `decision` MCP server
  (`guard_mutation`, `decide`, `route_agent`). Off without `OPENROUTER_API_KEY`.
- **core**: memories and instruction files are scanned for injected instructions, hidden HTML
  comments and invisible or bidirectional characters.
- **core**: `--with-slack` installs the Slack bot with its units rendered for the installing user.
- **core**: memory search is hybrid (dense and BM25, fused), a memory with a `state_key` replaces the
  older one with the same key without deleting it, and sessions in both engines start with a memory
  brief (`/memory/brief`, `memory.py brief`, MCP `memory_brief`).
- **core**: `evals/memory_benchmark.py` measures the memory against a Hermes-like baseline on a
  public synthetic dataset (`docs/memory-benchmark.md`); `docs/hermes-comparison.md` compares the
  guard with Hermes Agent's own checks, both ways.
- **core**: `pak`, one command line (`doctor`, `guard`, `memory`, `lessons`, `task`, `eval`,
  `import hermes`), linked as `~/.local/bin/pak`.
- **core**: an autonomous worker (`pak task`): a throwaway clone, the guards on and a spending cap;
  the result is a patch reviewed by a second call with no tools, never a commit. The engine runs in
  a container (`bin/worker/Dockerfile`, `pak task image`) with `--network none`, a read-only root
  and no capabilities; its only way out is a proxy on the host (`bin/egress.py`) that allows the
  model API and `PAK_WORKER_EGRESS` and records every request. Without Docker or a key a task
  refuses to run; `--isolation host` runs it on the host and must be asked for.
- **core**: the guard reads each command as bash would run it (`bin/shell_parse.py`): quotes,
  escapes, variables, wrappers such as `sudo` and `timeout`, global options such as `git -C`, and
  the code inside `bash -c`, `eval` and `$(…)`. New rules: the history git cannot recover
  (`git_history`), the hooks folder (`hooks_path`) and code the text does not show
  (`dynamic_code`). Secrets piped to the network are stopped by the command's structure.
- **core**: `evals/guard_benchmark.py` scores the guard on a held-out set written before the
  changes and frozen by its sha256: 57 of 91 harmful commands stopped and 26 of 30 harmless ones
  allowed, against 36 and 24 for Hermes Agent's checks (`docs/guard-benchmark.md`). `pak eval
guard` runs it, and a test fails below the recorded floor.
- **core**: snapshots (`pak snapshot`, `bin/snapshot.py`): every session in both engines and every
  challenge copies the repository to `~/.pak/snapshots`, outside it and without touching its
  `.git`. `restore` writes a copy back and deletes nothing. `pak doctor` reports them and the
  worker.
- **core**: lessons tie each control to its incident and its expiry (`pak lessons`), and the memory
  is consolidated every night (`agent-memory-consolidate.timer`, near-duplicates marked replaced).
- **core**: guard corpus of 279 commands and URL corpus of 56, run through both engines, and
  `bin/tests/guard-e2e/run.sh`, which runs the real Claude Code and OpenCode against a scripted
  model.

### Bug Fixes

- **core**: the OpenCode plugins never ran on OpenCode 2, which loads only a default export, and
  their switch was never set. They now load in every project, on by default.
- **core**: the Slack bot answered every channel when `SLACK_CHANNEL_IDS` was empty. It is closed
  by default now, and `SLACK_ALLOWED_USERS` lists who it answers.
- **core**: the injection guard never matched `.env`, and it read `### System requirements` as a
  role marker.
- **core**: `memory_service` listened on every interface; it listens on `127.0.0.1` now
  (`MEMORY_SERVICE_HOST`).
- **core**: the OpenCode session plugin cleaned old files from the `temp/` of the session's project;
  loaded in every project, it would have reached any repo. It cleans only the kit's own `temp/`.
- **core**: the guard let `halt`, `telinit 0`, `systemctl halt` and `kill -1` through, and blocked a
  commit message that quoted a delete.
- **core**: the guard let through `git push --delete origin <branch>`, `rsync --delete`, `DELETE`
  without `WHERE`, `FLUSHALL`, `source <(curl …)` and clearing the shell history, and it stopped
  `man shutdown` and a `python -c` that only prints.
- **core**: systemd units and `.env` are rendered for the installing user and clone path. They used
  to be installed with raw `<user>` placeholders.
- **core**: `memory_service` gets its token from a `.env` built from the template. The literal
  `false` of `MEMORY_ALLOW_NO_AUTH` used to skip it.
- **core**: the installer keeps submodules at their pinned commits.
- **core**: the first start waits for `memory_service` while it downloads the embedding model.

### Changed

- **core**: the core install runs no downloaded script: Docker and Node come from apt repositories.
- **core**: development toolchains moved behind `--with-dev-tools`. The AWS and GitLab CLIs are gone.
- **core**: default models updated to Fable 5.1, Opus 5.5, Sonnet 5.5 and Haiku 5.5.
- **core**: the pre-commit tools are now regular files in `scripts/`, with their tests. The `scripts`
  submodule is gone.
- **core**: OpenCode is installed at the version the guards were proven against
  (`configs/opencode.version`).
- **core**: memory categories are English (`security`, `style`, `systems`, `business`, `other`); the
  old Spanish names are still read.
- **core**: OpenCode no longer gets Claude Code's own memory folder: both engines share one memory.

## [1.0.1] - 2026-09-08

### Features

- **core**: initial release — personal Claude Code + OpenCode setup with a local memory brain,
  safety guardrails, and BMAD-based agent creation.
