# Install Test

> **Date**: 2026-11-08 | **Result**: 32 of 32 checks passed, 1 skipped | **Host**: Docker 29.9.0 on WSL2

`bin/tests/install-container/run.sh` installs the kit on a clean machine and checks that it works.
This page records the last full run.

## Setup

- **Machine:** `ubuntu:24.04`, pinned by digest, with systemd as PID 1 and its own Docker daemon.
- **Account:** `someone`, an ordinary sudo account that exists before the install. It stands for
  whoever installs the kit.
- **Path:** `~/work/tools/pak`, to prove the kit doesn't expect a user or a folder name.
- **Source:** a fresh `git clone` of a throwaway snapshot of the working tree (964 files). The real
  history gets no commit.

## Results

| Run                                                   | Exit |
| ----------------------------------------------------- | ---- |
| `bash bin/install.sh --yes`                           | 0    |
| `bash bin/install.sh --yes --with-bmad --language es` | 0    |
| `bash bin/install.sh --yes --with-opencode`           | 0    |
| `bash bin/install.sh --yes --with-slack`              | 0    |

The whole test, checks included, took 13m 24s (run `20261108T172535`).

| Area     | What was checked                                                                                                                                        |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Accounts | `getent passwd` is the same before and after: the install added no account                                                                              |
| Identity | `agent-memory.service` and `opencode-server.service` run as the installing user                                                                         |
| Paths    | Units point at this clone, and no `<user>` placeholder reached the machine                                                                              |
| Secrets  | `.env` has mode 600 and gets a generated token                                                                                                          |
| Memory   | Qdrant and `memory_service` answer, a call without a token gets a 401, and a memory is written, found again and survives a re-install                   |
| Guards   | The guard hooks are registered, Stage 2 is off and auto-approval is off, and `bin/tests/guard-e2e/run.sh` blocks in the real Claude Code                |
| Worker   | `bin/tests/guard-e2e/worker.sh`: a task becomes an approved patch with no commit, the guard blocks inside it, and the spending cap stops a task         |
| CLI      | `pak` is on the PATH and `pak doctor` finds every core layer; the nightly consolidation timer is active and runs                                        |
| Hooks    | The session hook prints the language policy                                                                                                             |
| Claude   | Claude Code, its default model and the 12 plugins are installed                                                                                         |
| Options  | BMAD stays inactive by default and activates on request; `--language` changes the conversation and leaves the repo surfaces in English                  |
| Pins     | Submodules stay at their recorded commits                                                                                                               |
| OpenCode | Version 2.2.5 as pinned, 14 agents with BMAD active, language policy delivered, the 5 plugins load in every project, and the server answers on its port |
| Slack    | The units are rendered for the installing user and this clone; the bot is closed (`SLACK_ALLOWED_USERS` empty) and not started without tokens           |

## Corrections to the previous run

The run of 2026-11-07 reported OpenCode as installed. It was OpenCode 1.19.5: the installer asked
for the `opencode-ai` package, which stays on the 1.x line, while OpenCode 2 is published as
`@opencode/cli`. On OpenCode 2 the kit's plugins did not load and the server unit failed on a flag
that no longer exists. This run is the first one with OpenCode 2, and it checks the plugins and the
server for real.

## What this run does not prove

- `--with-tts` and `--with-dev-tools` did not run.
- The engines ran against a scripted model (`bin/tests/guard-e2e/fake_model.py`): no real model was
  called, and Stage 2 did not run, because the test has no provider key.
- The OpenCode engine run was skipped (`PAK_SKIP_OPENCODE_ENGINE=1`): the guard of the host that ran
  the test forbids starting a model outside its own allowlist, the scripted one included. It passed in
  the earlier runs of the same day.
- OpenCode reports its missing API keys as warnings, as expected on a machine without them.
- Only Ubuntu 24.04 on x86-64 was tested.
- The GitHub Actions workflow has not run yet: the repository isn't published.

## How to reproduce it

```bash
bash bin/tests/install-container/run.sh          # removes the container at the end
bash bin/tests/install-container/run.sh --keep   # leaves it running to look inside
```

It needs Docker with privileged containers, and about 15 minutes. The evidence goes to
`temp/install-test/<timestamp>/`: the logs of each run, `summary.txt` and the account lists.
