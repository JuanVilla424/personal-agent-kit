# 💻 Development Guide

How to develop the **Personal Agent Kit**: the daily loop, the quality gates the hooks and the
pipeline enforce, and how a change travels from `dev` to `main`.

## 📚 Table of Contents

- [Local Environment](#-local-environment)
- [Daily Loop](#-daily-loop)
- [Quality Gates](#-quality-gates)
- [Git Hooks](#-git-hooks)
- [Branches and Releases](#-branches-and-releases)
- [Submodules](#-submodules)
- [Configuration and Secrets](#-configuration-and-secrets)
- [License](#-license)

## 🔧 Local Environment

**`bash bin/install.sh` sets up the kit itself. To run every check, prepare the clone like the
pipeline does**:

1. **Submodules:** check out their pinned commits:

   ```bash
   git submodule update --init --recursive
   ```

2. **Python:** the root virtual environment carries the tools, the services, the tests and the git
   hooks:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt -r requirements.dev.txt
   .venv/bin/pip install -r local/scripts/memory_index/requirements.txt
   .venv/bin/pip install -r local/scripts/notify/requirements.txt
   .venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
   ```

3. **OpenCode plugins:** their tests run with [Bun](https://bun.sh) 1.3.14, the version the
   pipeline uses.

4. **End-to-end checks:** Docker and the `claude` CLI, only for the checks that run the real
   engines or the worker's container.

## 🔁 Daily Loop

**Every change follows the same loop**:

1. **Sync:** `git fetch origin && git pull --rebase origin dev`.
2. **Change:** write the code and its tests together. AI agents follow [AGENTS.md](AGENTS.md).
3. **Check:** run the [quality gates](#-quality-gates) that cover what you touched.
4. **Commit:** one commit per task, `type(core): description in lower case`, as
   [VERSIONING.md](VERSIONING.md) describes. If a hook fails or fixes a file, fix what it reports,
   stage the changes and commit again.
5. **Push in two steps:** the first `git push` lets `validate-commit` add the icon to the message,
   amend the commit and stop the push. Run the same `git push` again.

## ✅ Quality Gates

**Run the checks that cover your change before you push; the pipeline repeats the first four**:

| Area                                      | Command, from the repository root                            | Also runs in                                  |
| ----------------------------------------- | ------------------------------------------------------------ | --------------------------------------------- |
| Python tests, with the 96 % coverage gate | `.venv/bin/python -m pytest -m "not integration"`            | `ci.yml`, job `python`                        |
| Language policy                           | `.venv/bin/python helpers/ai18n/src/ai18n.py check --root .` | `ci.yml`, job `python`                        |
| OpenCode plugins                          | `(cd .opencode && bun test)`                                 | `ci.yml`, job `plugins`                       |
| Everything the hooks check                | `.venv/bin/pre-commit run --all-files`                       | `ci.yml`, job `pre-commit`, and the git hooks |
| The guards in the real engines            | `bash bin/tests/guard-e2e/run.sh`                            | —                                             |
| The worker in its container               | `bash bin/tests/guard-e2e/worker.sh`                         | —                                             |
| A clean install, about 20 minutes         | `bash bin/tests/install-container/run.sh`                    | —                                             |
| The guard's corpus and held-out benchmark | `pak eval guard`                                             | —                                             |

`pre-commit run --all-files` checks only the files git tracks: stage a new file before you run it.
The two `guard-e2e` checks drive the real engines with a scripted model, so they need no key and
spend nothing.

## 🪝 Git Hooks

**`.pre-commit-config.yaml` stops a change before it leaves your machine. The code of its local
hooks lives in `scripts/`, in this repository**:

- **On every commit and push:** whitespace and end of files, YAML and JSON syntax, merge markers,
  large files, debug statements and private keys; Python format (`black`) and lint (`pylint`);
  YAML format (`yaml-format`, `yml-format`); the copyright year (`bump-year`); `CHANGELOG.md`
  (`generate-changelog`); and Markdown (`prettier`).
- **Only on push:** `validate-commit` checks the message and adds its icon, and
  `commit-msg-version-check` bumps the version when the message carries a versioning keyword.

Never skip them with `--no-verify`: fix what they report.

## 🌿 Branches and Releases

**One working branch, and a version only when a release is requested**:

- **Work on `dev`.** `dev` reaches `main` through a pull request when it is ready; never push to
  `main`.
- **Release a change** by ending its commit message with `[patch candidate]`, `[minor candidate]`
  or `[major candidate]`. The pre-push hook runs `bump2version`, which updates every file
  `.bumpversion.cfg` lists: `pyproject.toml`, the version badge of `README.md` and `.bmadrc.yaml`.
- **The details** are in [VERSIONING.md](VERSIONING.md): the commit types, the keywords and how
  `CHANGELOG.md` is kept.

[ARCHITECTURE.md](ARCHITECTURE.md) describes the components these checks cover.

## 🧩 Submodules

**Two submodules stay pinned to exact commits. Never edit them from here**:

| Path                                  | What it is                                                                                |
| ------------------------------------- | ----------------------------------------------------------------------------------------- |
| `helpers/ai18n`                       | The language policy resolver, [JuanVilla424/ai18n](https://github.com/JuanVilla424/ai18n) |
| `local/scripts/chatterbox-tts-server` | The optional offline voice engine                                                         |

Change a submodule in its own repository, then move the pin here as a reviewed change:

```bash
git submodule update --remote helpers/ai18n
git add helpers/ai18n
```

## 🔐 Configuration and Secrets

**Configuration stays out of git**:

- **Local settings** go in the root `.env`, which git ignores; `.env.template` lists every
  variable with a placeholder. Only `local/scripts/notify/` and `local/monitoring/` keep their own
  `.env`.
- **Every variable is documented:** `utils/tests/test_env_template_guard.py` fails when the code
  reads a variable the templates do not list.
- **Never** commit a credential, a key or a certificate.

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file
included in this repository.
