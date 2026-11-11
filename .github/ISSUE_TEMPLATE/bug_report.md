---
name: Bug report
about: Report a problem with the guard, the memory, the worker, the installer or the engine wiring
title: ""
labels: ""
assignees: ""
---

**Describe the bug**
A clear and concise description of what the bug is.

**Component**
The part that failed: the guard (`bin/auto_guard.py`, `bin/url_guard.py`), the memory
(`memory_service`, MCP), the worker (`pak task`), the snapshots, the installer, a Claude Code hook
or an OpenCode plugin, a persona, or the documentation.

**Command or engine**
The command you ran, such as `pak guard "git push --force"` or `bash bin/install.sh --yes`, or the
engine and the action it was about to take.

**Expected behavior**
What you expected to happen, and the protocol or document that supports it.

**Actual behavior**
What happened instead, including the full output or error.

**`pak doctor`**

```text
# output of pak doctor
```

**Environment:**

- PAK version: [the `current_version` in `.bumpversion.cfg`, and `git rev-parse --short HEAD`]
- Engine: [e.g. Claude Code 2.1.263, OpenCode 2.x]
- Python version: [e.g. 3.12.3]
- OS: [e.g. Ubuntu 24.04]

**Additional context**
Add any other context about the problem here. Never paste a key, a token or the content of `.env`.
