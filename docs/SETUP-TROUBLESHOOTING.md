# Troubleshooting Guide — Personal Agent Kit

**Maintained by:** Kai 🔧

---

## Quick Reference — Required Tools

| Tool         | Purpose                      | Check                            | Install                                                |
| ------------ | ---------------------------- | -------------------------------- | ------------------------------------------------------ |
| `python3`    | Runtime + venv               | `python3 --version`              | `sudo apt install python3`                             |
| `git`        | Version control + submodules | `git --version`                  | `sudo apt install git`                                 |
| `jq`         | JSON parsing                 | `jq --version`                   | `sudo apt install jq`                                  |
| `yq`         | YAML parsing                 | `yq --version`                   | see below                                              |
| `curl`       | HTTP requests + downloads    | `curl --version`                 | `sudo apt install curl`                                |
| `node`       | Claude Code CLI runtime      | `node --version` (need ≥20)      | see below                                              |
| `claude`     | Claude Code CLI              | `claude --version`               | `npm install -g @anthropic-ai/claude-code`             |
| `docker`     | Container runtime            | `docker --version`               | [Docker docs](https://docs.docker.com/engine/install/) |
| `pre-commit` | Git hooks                    | `.venv/bin/pre-commit --version` | installed via `requirements.dev.txt`                   |

---

## 1. Claude Code

### `claude: command not found`

**Symptom:** Running `claude` in the terminal returns `command not found`.

```bash
# Install via npm
npm install -g @anthropic-ai/claude-code

# Verify
claude --version
```

If `npm` is not available, install Node.js first:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

**Verification:** `claude --version` outputs the installed version number.

### Model not set to opusplan / effort not max

**Symptom:** Claude Code uses the wrong model or effort level is not `high`.

```bash
# Set model globally
claude config set --global model opusplan

# Add env vars to ~/.bashrc
echo 'export CLAUDE_CODE_EFFORT_LEVEL=max' >> ~/.bashrc
echo 'export CLAUDE_CODE_SUBAGENT_MODEL=claude-sonnet-5-5' >> ~/.bashrc
source ~/.bashrc
```

**Verification:** `claude config get model` returns `opusplan`; `echo $CLAUDE_CODE_EFFORT_LEVEL` returns `max`.

### Claude Code not picking up MCP servers

**Symptom:** MCP tools (context7, memory, github) are unavailable in the session tool list.

1. Verify `~/.claude/settings.json` has the MCP server entries
2. Restart Claude Code completely (not just reload)
3. Check Node.js version: `node --version` must be ≥20

**Verification:** After restart, MCP tools appear in the session tool list.

---

## 2. Python / Virtual Environment

### `.venv` does not exist

**Symptom:** Running any `.venv/bin/python` command returns `No such file or directory`.

```bash
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt -r requirements.dev.txt
```

**Verification:** `.venv/bin/python --version` returns the Python version without errors.

### `ModuleNotFoundError` when running a script

**Symptom:** Script fails with `ModuleNotFoundError` when run with `python3`.

The system Python is being used instead of `.venv`. Always use:

```bash
.venv/bin/python script.py
# never: python3 script.py
```

**Verification:** `.venv/bin/python <script>.py` runs without import errors.

### `.venv` is corrupted or has wrong packages

**Symptom:** Import errors persist after `pip install`, or packages show incorrect versions.

```bash
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements.dev.txt
```

**Verification:** `.venv/bin/pip list` shows expected packages at correct versions.

---

## 3. Pre-commit Hooks

### Hooks not running on commit/push

**Symptom:** Pre-commit hooks do not execute on `git commit` or `git push`.

```bash
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
```

**Verification:** `git commit --dry-run` triggers hook output in the terminal.

### Hook fails on first push (expected behavior)

**Symptom:** First `git push` exits with code 1 after the `validate-commit` hook adds an emoji.

The two-push flow is intentional:

- **Push 1** → `validate-commit` adds emoji icon, `commit-msg-version-check` bumps version if `[patch candidate]` present → exits 1
- **Push 2** → all hooks pass, code reaches remote

Just run `git push` again.

**Verification:** Second `git push` completes with exit code 0 and code reaches the remote.

### `bump2version` fails: `Did not find '## [Unreleased]'`

**Symptom:** `bump2version` aborts with `Did not find '## [Unreleased]'` when processing CHANGELOG.md.

The `CHANGELOG.md` is missing the unreleased section header. Add it:

```bash
sed -i '1s/^/## [Unreleased]\n\n/' CHANGELOG.md
git add CHANGELOG.md
git commit --amend --no-edit
```

**Verification:** `head -3 CHANGELOG.md` shows `## [Unreleased]` on the first line.

### `pre-commit run --all-files` modifies files and fails

**Symptom:** Hooks auto-format files and exit non-zero; re-running fails because modified files are not staged.

Normal behavior — hooks auto-fix files. Re-stage and re-run:

```bash
git add -u
git commit --amend --no-edit
```

**Verification:** `git add -u && .venv/bin/pre-commit run --all-files` exits 0 with no further modifications.

---

## 4. Git Submodules

### Submodule directory is empty

**Symptom:** `helpers/ai18n/` exists but contains no files after clone or pull.

```bash
git submodule update --init --recursive
```

**Verification:** `git submodule status` shows no `-` prefix; directory contains files.

### Submodule shows as modified (dirty) after pull

**Symptom:** `git status` shows `modified: helpers/ai18n (new commits)` or similar submodule drift.

```bash
git submodule update --init --recursive
```

**Verification:** `git submodule status` shows no `+` prefix; `git status` shows clean working tree.

### Cannot push: submodule at wrong commit

**Symptom:** Push rejected because submodule pointer is at an unexpected or local-only commit.

Submodules are read-only from this repo — never edit files inside them directly. Changes go to the submodule's own repo.

**Verification:** `git submodule status` shows no `+` prefix.

---

## 5. jq / yq

### `jq: command not found`

**Symptom:** a guard or an installer step fails silently or shows `jq: command not found`.

```bash
sudo apt-get install -y jq
# verify
jq --version
```

**Verification:** `jq --version` returns a version string (e.g., `jq-1.6`).

### `yq: command not found`

**Symptom:** the installer can't read `configs/model-protocol-map.yaml`, or shows `yq: command not found`.

```bash
# Install Go-based yq binary (recommended)
YQ_VERSION="v4.44.3"
curl -sL "https://github.com/mikefarah/yq/releases/download/${YQ_VERSION}/yq_linux_amd64" \
    -o /tmp/yq && chmod +x /tmp/yq && sudo mv /tmp/yq /usr/local/bin/yq
# verify
yq --version
```

**Verification:** `yq --version` returns `yq (https://github.com/mikefarah/yq/) version v4.x.x`.

### `yq` installed but wrong version (Python yq vs Go yq)

**Symptom:** `yq` commands return unexpected syntax errors or wrong output format (Python yq has different syntax).

```bash
# Check which one is installed
yq --version  # Go yq shows: yq (https://github.com/mikefarah/yq/) version v4.x.x
              # Python yq shows: yq x.x.x

# Remove Python yq if needed
pip uninstall yq
# Install Go yq (see above)
```

**Verification:** `yq --version` shows `v4.x.x` from `github.com/mikefarah/yq`.

---

## 6. Docker / Redis

### `sysctl "vm.overcommit_memory" is not in a separate kernel namespace`

**Symptom:** Docker Redis (or Qdrant) container logs show a sysctl warning; container may fail to start.

This cannot be set from within a container. Apply it on the host:

```bash
sudo sysctl vm.overcommit_memory=1
echo "vm.overcommit_memory = 1" | sudo tee -a /etc/sysctl.conf
```

**Verification:** `sysctl vm.overcommit_memory` returns `vm.overcommit_memory = 1`; container starts without warning.

### `docker compose up` fails: port already in use

**Symptom:** `docker compose up` fails with `address already in use` on a specific port.

```bash
sudo lsof -i :<PORT>
# kill the conflicting process or change the port in docker-compose.yml
# the brain's ports are set in .env instead: INSTALL.md, "Own Ports for the Brain"
```

**Verification:** `docker compose up` starts without port conflict errors; container shows `healthy` status.

---

## See Also

- [Architecture](../ARCHITECTURE.md) — system overview
- `bin/install.sh` — automated setup script
