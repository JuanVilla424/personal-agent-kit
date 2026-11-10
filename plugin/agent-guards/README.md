# agent-guards

![Type](https://img.shields.io/badge/Type-Claude%20Code%20Plugin-blue.svg)
![Status](https://img.shields.io/badge/Status-Local%20to%20personal--agent--kit-yellow.svg)

Security guardrails and skills from `personal-agent-kit`, packaged as a Claude Code plugin —
an internal way of grouping this inside the same repo, tested locally with `--plugin-dir`. Not
installed or distributed to other projects.

## What it includes

**Hooks** (`hooks/hooks.json`, adapted copies of `local/hooks/`):

- `rm-guard.sh` — blocks recursive/forced `rm` over generated or sensitive directories.
- `pre-write-guard.sh` — blocks hardcoded secrets, credential files, versioned filenames, and
  checks `.py`/`.sh` syntax before writing.
- `post-write-judge.sh` + `judge_against_agents.py` — non-blocking semantic judge against the
  host project's `AGENTS.md` (reads `${CLAUDE_PROJECT_DIR}/AGENTS.md`).
- `token-check-reminder.sh` / `pre-compact-reminder.sh` — non-blocking reminders.

**Skills** (`skills/`, copies of `.claude/skills/`): `bmad-component`, `fastapi-project-service`,
`pre-compact`.

## What it deliberately does NOT include

`post-plan-approval.sh` (writes to this repo's own `TASKS.md`), `session-start.sh`, and
`tts_hook.py` (full TTS with all its persona/engine infrastructure) — all tied to
`personal-agent-kit` conventions that don't generalize to another project.

## Adaptations vs. the original copies

`judge_against_agents.py` and `post-write-judge.sh` no longer assume they live inside this
repo's own `local/hooks/` — they use `${CLAUDE_PROJECT_DIR}` (the host project's AGENTS.md) and
`python3` from PATH instead of a `.venv` relative to their own location.

## Try it locally (no marketplace)

```bash
claude --plugin-dir ./plugin/agent-guards
```

## Scope: `personal-agent-kit` only

This plugin is managed and lives ONLY in this repo — it is not distributed to other projects,
whether via marketplace or any other way. The content of `bmad-component` and
`fastapi-project-service` references this package's own paths (`.bmad/local/`,
`memory_index/memory_service.py`) on purpose — it doesn't need to be generic because it never
leaves here. `--plugin-dir` is only for testing the mechanism locally, not a step toward
external distribution.
