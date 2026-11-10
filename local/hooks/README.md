# Claude Code Hooks — personal-agent-kit

Hooks **versioned in the repo** (unlike the ones in `~/.claude/hooks/`, which are
per-machine). Validate the agent's writes against the project's conventions.

| Hook                             | Event                                        | Blocks         | What it does                                                                                                                                                                                                                                                                                                                                                                 |
| -------------------------------- | -------------------------------------------- | -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pre-write-guard.sh`             | `PreToolUse` · matcher `Write\|Edit`         | yes (`exit 2`) | **Fast, deterministic** check on the incoming text: secret paths (`.env`, `*.pem`…), versioned filenames (`-vN`), hardcoded secrets, and syntax (`.sh`/`.py`) on Write.                                                                                                                                                                                                      |
| `rm-guard.sh`                    | `PreToolUse` · matcher `Bash`                | yes (`exit 2`) | Blocks recursive+forced `rm` (`-rf`/`-fr`/`-r -f`) when the target is `.git`/`.venv`/`venv`/`node_modules`/`__pycache__`/`dist`/`build` as a full path segment — never by substring, so `.venv/bin/python3 ...`, `cat .env.template`, or `npm install` are never blocked. Replaces `.claude/scripts/validate-bash.sh` (never registered, used to block by substring).        |
| `auto-guard.py`                  | `PreToolUse` · matcher `Bash`                | yes (`exit 2`) | The shared guard rules (`bin/auto_guard.py`, Stage 1) on every shell command: a block exits 2, a challenge asks the human through the native dialog, and a guard that cannot judge blocks. Same rules as `.opencode/plugins/auto-guard.js`. A challenge also snapshots the session's repository in the background (`bin/snapshot.py`). See `protocols/decision-protocol.md`. |
| `url-guard.py`                   | `PreToolUse` · matcher `WebFetch\|WebSearch` | yes (`exit 2`) | `bin/url_guard.py` on every fetched URL and search query: loopback, private and metadata hosts, names that resolve to them, credentials and secrets in the URL.                                                                                                                                                                                                              |
| `post-write-judge.sh`            | `PostToolUse` · matcher `Write\|Edit`        | no (warns)     | On the file already on disk: **syntax** (`.sh`/`.py`/`.yml`) + **semantic judge** (`judge_against_agents.py`) vs `AGENTS.md`. Emits the warning as `additionalContext` (exit 0) — Claude sees it as a system reminder, never blocks.                                                                                                                                         |
| `post-plan-approval.sh`          | `PostToolUse` · matcher `ExitPlanMode`       | no             | Dumps the just-approved plan (the most recent one in `~/.claude/plans/`) to the end of `TASKS.md`, "Approved plan history" section — a substitute for `TodoWrite` on this surface.                                                                                                                                                                                           |
| `pre-compact-reminder.sh`        | `PreCompact` · matcher `manual\|auto`        | no             | Reminds to invoke the `pre-compact` skill (update only `temp/current-context.md`, max 100 lines) before compacting.                                                                                                                                                                                                                                                          |
| `token-check-reminder.sh`        | `UserPromptSubmit`                           | no             | Reminds about the `protocols/token-management.md` thresholds (120k/150k/170k of 200k) on every prompt — it can't see the real token usage, it just points at the protocol.                                                                                                                                                                                                   |
| `.claude/hooks/session-start.sh` | `SessionStart`                               | no             | Cleans up `temp/` (files >7 days, logs >14 days), injects `.bmad/local/orientation.txt` and, in the background, snapshots the session's repository (`bin/snapshot.py`) at session start. The only hook in this list that does NOT live in `local/hooks/` — it's in `.claude/hooks/` (versioned the same way, just for that one file's historical convention).                |
| `.claude/hooks/tts_hook.py`      | `Stop` and `Notification`                    | no             | Reads the payload, extracts the text (transcript for `Stop`, `message` directly for `Notification`), cleans/truncates it, and delegates synthesis+playback to a detached worker (`tts_speak_worker.py`, `.venv`) — never blocks. Full detail: `docs/stories/tts-hook-persona.md`.                                                                                            |

The judge (`judge_against_agents.py`) reads the file + `AGENTS.md`, asks a fast
model (`claude -p`, Haiku) whether it complies with the conventions, and reports
violations in English. It's **best-effort**: if `claude` isn't available, the file
type isn't code, or something fails → it doesn't block (`exit 0`). It never wedges
the session.

## Design

- **pre = cheap / before**: cuts off secrets and broken syntax before touching disk.
- **post = expensive / after**: the judge (an LLM call) doesn't slow down every
  keystroke; it reviews the result and, if it doesn't comply, leaves the detail for
  the agent to fix.
- **Anti-recursion**: the judge runs `claude -p` with `PAK_HOOK_RUNNING=1`; both
  hooks exit immediately if they see that variable (keeps the judge from triggering
  itself).
- **In the worker's container** (`pak task`), `bin/pak_worker.py` registers only the
  four `PreToolUse` guards of `install-hooks.py`, at their paths under the read-only
  `/pak`, and points the guard's log into the task's folder.

## Registration (in `~/.claude/settings.json`)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/local/hooks/rm-guard.sh",
            "timeout": 5000
          }
        ]
      },
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/local/hooks/pre-write-guard.sh",
            "timeout": 10000
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/local/hooks/post-write-judge.sh",
            "timeout": 60000
          }
        ]
      },
      {
        "matcher": "ExitPlanMode",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/local/hooks/post-plan-approval.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "PreCompact": [
      {
        "matcher": "manual|auto",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/local/hooks/pre-compact-reminder.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/local/hooks/token-check-reminder.sh",
            "timeout": 5000
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/.claude/hooks/session-start.sh",
            "timeout": 10000
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/.claude/hooks/tts_hook.py",
            "timeout": 5000
          }
        ]
      }
    ],
    "Notification": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "<REPO>/.claude/hooks/tts_hook.py",
            "timeout": 5000
          }
        ]
      }
    ]
  }
}
```

Replace `<REPO>` with the repo's absolute path. `local/hooks/install-hooks.py`
registers them idempotently (re-run it after cloning or updating `MANAGED`).
