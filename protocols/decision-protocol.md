# 🛡️ Decision Protocol — the guard, and how to decide

> How every agent in this kit decides before it acts: the guard that judges each mutation, the
> quarantine that replaces deleting, and the decision engine that quantifies a choice.

---

## How to use the guard — read this before any mutation

The guard has **one rule set** (`BLOCK_RULES` in `bin/auto_guard.py`) and two stages:

- **Stage 1 — rules**: regex, instant, no LLM. Always on.
- **Stage 2 — judgment**: the decision engine (`bin/decision.py`, one model behind OpenRouter's
  Decisions API). **Optional**: it runs only with `OPENROUTER_API_KEY` in `.env`. Without the key
  it is off, which is a normal state: Stage 1 still decides, and every challenge asks the human.

`python3 bin/auto_guard.py --status` prints what is on.

### What is checked automatically

| What the agent does    | Claude Code (global hooks)                     | OpenCode (plugins, in every project) |
| ---------------------- | ---------------------------------------------- | ------------------------------------ |
| Any shell command      | `local/hooks/auto-guard.py`, `rm-guard.sh`     | `auto-guard.js`, `rm-guard.js`       |
| Writing or editing     | `local/hooks/pre-write-guard.sh`               | `pre-write-guard.js` (patches too)   |
| Fetching a URL, search | `local/hooks/url-guard.py`                     | `url-guard.js`                       |
| Starting a session     | `session-start.sh` scans the instruction files | —                                    |
| Storing a memory       | `memory_service` refuses injection signals     | the same service                     |

The hooks and plugins call the same Python code, so a rule means the same thing in both engines.
A guard that cannot judge (a crash, a timeout, a missing interpreter) **blocks**: it never lets a
command through. `bin/tests/guard-e2e/run.sh` proves the wiring in the real engines, with a
scripted model and no key.

### When to ask for the full judgment yourself

Before any mutation that is not a plain shell command (an API call, a script that changes data),
or whenever you are unsure:

- MCP tool, in both engines: `guard_mutation(action="<what you will run>", intent="<what the human asked>")`
- CLI: `python3 bin/auto_guard.py "<action>" --intent "<what the human asked>" [--json]`

It prints `allow`, or the result followed by what to do. `--stage1-only` runs only the rules,
which is what the hooks do.

### Results and exactly what to do

| Result               | Means                                                 | What to do                                                                                                                 |
| -------------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `allow`              | no rule matched, and Stage 2, when on, judged it safe | it runs                                                                                                                    |
| `challenge`          | a rule or the engine wants the human's approval       | ask the human. Claude Code shows its own dialog; in OpenCode the message carries the exact `approve` command for the human |
| `block`              | agents never run this                                 | find a safer path or ask the human to run it. **Nothing approves a block**                                                 |
| `halt`               | 3 denials in a row or 20 in total in one session      | stop mutating in this session and tell the human                                                                           |
| `engine_unavailable` | Stage 2 failed twice; it is **not** a verdict         | do not go on alone: retry later or ask the human                                                                           |

### Approving a challenge

The human approves one exact action, once, from a terminal:

```bash
python3 bin/auto_guard.py approve <hash>    # the hash, or a unique prefix of 8 or more
```

The approval is keyed to the exact intent and action, works once, and expires in 30 minutes
(`--ttl-min` changes it). `approve` refuses to run without a terminal, and the guard blocks any
command that runs it or touches `configs/auto-guard.json` or the approvals file: an agent cannot
approve itself.

**Auto-approval** is off. `configs/auto-guard.json` → `auto_approve.enabled: true` lets every
challenge pass and logs each one in `logs/auto_guard_log.jsonl` with severity `auto_approved`.
Only the human edits that file. A block is never auto-approved, and a failed evaluation only when
`applies_to` lists `engine_unavailable`, which is fail-open.

### The rules

| Group    | Severity          | What                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| -------- | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| destroy  | block             | force push, `--mirror` included; `git reset --hard`, `git stash drop/clear`, discarding the work tree; destroying what git keeps to undo (`branch -D`, `reflog expire`, `update-ref -d`, `filter-branch`, `gc --prune=now`); `find -delete`, `git clean`, `rsync --delete`; `DROP DATABASE/TABLE/SCHEMA`, a `DELETE` without `WHERE`, `FLUSHALL`; `terraform destroy`; `kubectl delete`, `helm uninstall`; `docker rm/rmi/prune`; formatting or overwriting a disk; power off; `rm` and every other delete, from the shell or from inline code, or emptying a file through `/dev/null`; sending credentials out, a dump of the environment or a credential folder piped out included |
| security | block / challenge | disabling the audit logs, the firewall or the shell history (block); adding an SSH key, changing permission tiers, `chmod 777`, writing to the shell profile, cron or sudoers (challenge)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| trust    | block / challenge | running downloaded or decoded code: `curl … \| bash`, `bash <(curl …)`, `source <(curl …)`, `base64 -d … \| sh` (block); code the text never spells out: a program name built at run time, generated code for `eval` or `source` (challenge); scanning for credentials and reading a secret file into the session (challenge)                                                                                                                                                                                                                                                                                                                                                        |
| review   | block / challenge | skipping git hooks, approving a challenge or changing the guard's settings (block); changing `core.hooksPath`, deleting a remote branch (`--delete`, `:branch`, `--prune`), pushing to main, deploying to prod, a generic `--force` (challenge)                                                                                                                                                                                                                                                                                                                                                                                                                                      |

Every message names its rule, such as `auto-guard [rm_any]`. **Deleting is a human act:** the
agent's only way to remove something is `bin/quarantine.py mv <path>`, a reversible move with a
sha256 manifest checked after the move. With Stage 2 on, no engine verdict ever authorizes a
delete either (`delete_human_only`).

The corpus `evals/datasets/guard-corpus.jsonl` holds every case the rules must decide, more than
50 that must block and more than 50 that must pass, and runs through both engines on every test
run. `docs/guard-benchmark.md` measures the rules on commands they never saw.

### How the rules read a command

Every rule reads the command text, and also what bash will run (`bin/shell_parse.py`): quotes and
escapes removed, `$'…'` decoded, the variables the line itself assigns resolved, wrappers such as
`sudo`, `env`, `timeout` and `xargs` dropped, the global options of git, kubectl, helm, docker and
terraform dropped, and the code nested in `bash -c`, `eval`, `$(…)`, `<(…)`, `find -exec` and a
heredoc fed to a shell read too. Splitting a word with quotes or hiding it in a variable does not
get past a rule.

### False positives and what the rules cannot see

A command whose every program only reads (`grep`, `cat`, `head`, `tail`, `wc`, `ls`, `echo`,
`git grep|log|show`, and `man` without a pager of its own) does not trip the rules about running
something, so a search that mentions `DROP TABLE` passes. A heredoc body that nothing executes
(`cat > notes.md <<EOF`) turns a block into a challenge: it is text being composed. Inline Python
that can reach nothing outside itself and only prints to the terminal (`python3 -c
'print("shutdown")'`) is read as text, like a commit message. If a harmless command is blocked,
tell the human; never reshape it to slip past the rule.

The rules do not see what a script already on disk does, nor what inline code in another language
does beyond the words it contains: the corpus lists these as `known_evasion`. The guard is the
first line, not the only one: autonomous work runs in the worker's container, and every session
starts with a snapshot of the repository.

### Do NOT

- Retry, rephrase or split a command to get past the guard.
- Approve your own challenge, or edit `configs/auto-guard.json`.
- Turn the guards off (`OPENCODE_HOOKS_ENABLED=false`, Claude Code settings) to get something
  through.

---

## How to decide

1. **Every decision has a confidence.** When the risk is real, `decide(context, question, options)`
   gives the distribution, not only the winner: how close the other option was.
2. **Every mutation has a risk**, from read-only to critical. Know it before running:
   `guard_mutation()`.
3. **Every delegation has a fit.** Before handing work to another persona, know why that one:
   `route_agent(task)` reads `configs/agent-cards.json`.
4. **In doubt, escalate.** A confidence below 0.6 means the human decides.

`decide` and `route_agent` need the engine. With it off they answer `engine: off` or `escalate`:
decide yourself with the same discipline, or ask the human. They never invent an answer.

| Situation            | Rule                         | Tool               |
| -------------------- | ---------------------------- | ------------------ |
| About to mutate      | Know the risk before running | `guard_mutation()` |
| About to delegate    | Know why that persona        | `route_agent()`    |
| Weighing options     | Quantify the confidence      | `decide()`         |
| Confidence below 0.6 | Ask the human                | always             |
