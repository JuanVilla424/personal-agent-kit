# 📦 Installation

personal-agent-kit ships two installers in `bin/`. Both source `bin/_lib.sh` and are safe to re-run.

They run as your own user, from wherever you cloned the repo. They create no Linux user. Use an
account with `sudo`; running the whole installer under `sudo` is not needed.

## 📚 Table of Contents

- [Quick Install](#-quick-install)
- [Without Prompts](#-without-prompts)
- [Own Ports for the Brain](#-own-ports-for-the-brain)
- [OpenCode Only](#-opencode-only)
- [The Autonomous Worker](#-the-autonomous-worker-pak-task)
- [Diagnostic Utilities](#-diagnostic-utilities-bin)
- [Manual / Development Setup](#-manual--development-setup)
- [License](#-license)

## 🚀 Quick Install

```bash
git clone --recurse-submodules https://github.com/JuanVilla424/personal-agent-kit.git
cd personal-agent-kit
bash bin/install.sh
```

The default is a core install: Claude Code, the guards and hooks, a local Qdrant and the
`memory_service` (systemd, `:7700`). Each optional part is asked about when there is a terminal.

## 🔇 Without Prompts

```bash
bash bin/install.sh --yes                                   # core install
bash bin/install.sh --yes --with-bmad --language es         # with BMAD, replies in Spanish
bash bin/install.sh --dry-run --with-opencode               # print the plan, change nothing
```

| Option                                | Effect                                                     |
| ------------------------------------- | ---------------------------------------------------------- |
| `--yes`                               | Never prompt: use the defaults and the flags               |
| `--dry-run`                           | Print the resolved plan and exit                           |
| `--with-brain` / `--no-brain`         | Local Qdrant and `memory_service` (default: yes)           |
| `--with-bmad` / `--no-bmad`           | BMAD commands, subagents and OpenCode agents (default: no) |
| `--with-opencode` / `--no-opencode`   | OpenCode client (default: no)                              |
| `--with-tts` / `--no-tts`             | Voice tools and the Chatterbox fallback (default: no)      |
| `--with-slack` / `--no-slack`         | Slack bot and its timers, closed by default (default: no)  |
| `--with-dev-tools` / `--no-dev-tools` | LSP servers and language toolchains (default: no)          |
| `--language TAG`                      | Language for replies and voice, such as `es` or `pt-BR`    |
| `--opencode-model M`                  | `provider/model` for the OpenCode agents                   |

`--with-dev-tools` runs the official Rust, nvm and Bun install scripts. The core install runs no
downloaded script: Docker and Node come from signed apt repositories.

To add a part later, run the installer again with its flag.

## 🔢 Own Ports for the Brain

The brain uses two ports of this machine: Qdrant on `7633` (and `7634` for gRPC) and the
`memory_service` on `7700`. When something else already holds them, another kit for example, the
installer does not adopt that Qdrant: it skips the brain and says whose it is. Give this checkout
its own ports in `.env` and run the installer again:

| Setting               | Example                 |
| --------------------- | ----------------------- |
| `QDRANT_PORT`         | `7733`                  |
| `MEMORY_SERVICE_PORT` | `7800`                  |
| `MEMORY_SERVICE_URL`  | `http://localhost:7800` |

The three move together. On a port of its own the Qdrant container is `memory-qdrant-<port>`,
with its own volume and `<port>+1` for gRPC, so nothing is shared with the other kit. The
installer, `pak doctor` and `bash bin/brain-health.sh` count the service as this kit's only when
it accepts this kit's token, never because something answers on the address. The optional
monitoring stack in `local/monitoring/` scrapes the default Qdrant only.

## 🔌 OpenCode Only

```bash
bash bin/install-opencode.sh
```

It installs the OpenCode CLI, builds `~/.config/opencode/opencode.json` from the repo, checks the
provider API keys and installs the `opencode-server` unit (`127.0.0.1:4096`). It also sets up the
local brain if it isn't there. It takes the same options as `install.sh`.

## 🐳 The Autonomous Worker (`pak task`)

A task runs Claude Code in a container: no network but the model API, a read-only root, and nothing
mounted but a clone of the repository, the task's own HOME and the kit's guards. It needs:

- Docker, which the core install sets up.
- `ANTHROPIC_API_KEY`, or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` for a Claude
  subscription. Your login on this machine does not reach the container. The kit's end-to-end test
  runs a scripted model, so it does not exercise the subscription token.
- The image. `pak task image` builds `pak-worker:<version>-<hash>` from `bin/worker/Dockerfile`, with
  the Claude Code version in `configs/claude-code.version`. `pak task run` builds it when it is
  missing.

`PAK_WORKER_EGRESS` lets the container reach more destinations, such as `pypi.org:443`. Each refused
one is recorded in the task's `egress.jsonl`. Without Docker or a key, a task refuses to run and
says why. To run a task on this machine, with the guards as the only line, queue it with
`--isolation host`. `pak doctor` shows all of this on its Worker row.

## 🩺 Diagnostic Utilities (`bin/`)

- `bin/measure-footprint.sh` / `bin/count_tokens.py` — token footprint of the agent by layer (see `MODELS.md` §1).
- `bin/benchmark-models.sh` — re-run the model benchmark (`MODELS.md` §2). It uses your API credits.

## 🔧 Manual / Development Setup

1. **Initialize the submodules at their pinned commits**

   ```bash
   git submodule update --init --recursive
   ```

2. **Create a virtual environment and install dependencies**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt -r requirements.dev.txt
   ```

3. **Install the pre-commit hooks**

   ```bash
   pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

4. **Configure environment variables**

   Copy the root `.env.template` to `.env` (single config file for every tool) and fill in the required values. The only exceptions with their own `.env` are `local/scripts/notify/` and `local/monitoring/`. Never commit `.env` files. `utils/tests/test_env_template_guard.py` enforces that every env var read by the code stays documented in these templates.

[DEVELOPMENT.md](DEVELOPMENT.md#-local-environment) adds what the full test suite and the
end-to-end checks need.

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file
included in this repository.
