# Comparison with Hermes Agent

> **Date**: 2026-11-08 | **Hermes Agent**: release `v2026.9.24` (commit `f97608f`), the latest tag
> | **No model was called**

This page holds results only. No code, test or data of Hermes Agent is in this repository: the
comparison ran in a separate folder, against a checkout of Hermes' public repository.

## The guard

Hermes decides a shell command with two functions of its `tools/approval_detection.py`: a hardline
blocklist that never runs the command, and dangerous patterns that ask the user. PAK decides with
the rules of `bin/auto_guard.py`. Here "stopped" means blocked or asked: in both, the command does
not run on its own. Each guard's own code decided every case.

**PAK's corpus** (`evals/datasets/guard-corpus.jsonl`, 211 commands):

| Guard  | Stopped of the 119 that must stop | Blocked of the 96 that must block | Ran of the 89 harmless |
| ------ | --------------------------------- | --------------------------------- | ---------------------- |
| PAK    | **119**                           | **96**                            | **89**                 |
| Hermes | 51                                | 12                                | 70                     |

This corpus was written with PAK's rules and encodes PAK's policy: deleting is the human's (every
`rm` goes to quarantine), credentials never leave, an agent never approves itself. Hermes allows
an ordinary `rm` by design. So the gap measures how far Hermes is from that policy, not that its
checks are broken.

**Hermes' own cases** (the block and allow lists of its `tests/tools/test_hardline_blocklist.py`):

| Cases                     | PAK                                                                        |
| ------------------------- | -------------------------------------------------------------------------- |
| 89 that Hermes must block | stops all 89                                                               |
| 42 that Hermes must allow | lets 28 run; stops 13 `rm` commands (PAK's policy) and `print("shutdown")` |

Running Hermes' cases found four gaps in PAK, which PAK then covered with rules of its own: `halt`,
`telinit 0`, `systemctl halt`, and `kill -1` as the target (every process). It also found a false
positive: a commit message that quotes `rm -rf /` was blocked; a plain quoted `git commit -m` or
`git tag -m` message is now read as text. The one false positive left, `print("shutdown")` inside
`python3 -c`, stays: telling it apart from `bash -c "shutdown now"` by text alone is not safe.

### Commands written for neither guard

The corpus above was written together with PAK's rules, so it measures how well the rules fit the
cases they were written for. Two later sets measure commands neither guard was written for. Both
follow PAK's policy.

**Probe (2026-11-09):** 48 commands, 40 that reach a harm by another road and 8 harmless ones.

| Guard  | Stopped of the 40 harmful | Ran of the 8 harmless |
| ------ | ------------------------- | --------------------- |
| PAK    | 24                        | 6                     |
| Hermes | 12                        | 7                     |

**Held-out set (2026-11-09):** `evals/datasets/guard-heldout.jsonl`, 123 commands written before
any change to the guard and frozen (sha256 `9f74c1e6…930fb`). Two of them were already in PAK's
corpus, so they are left out: 91 harmful and 30 harmless are scored. Totals only, never case by
case, until the work was done:

| Guard                                   | Stopped of the 91 harmful | Ran of the 30 harmless |
| --------------------------------------- | ------------------------- | ---------------------- |
| PAK, before the parser                  | 35                        | 24                     |
| PAK, with the parser (`shell_parse.py`) | **57**                    | **26**                 |
| Hermes                                  | 36                        | 24                     |

Before the work the two were even: PAK's rules fit the corpus they were tuned on and missed most
variants they had not seen. Reading the command the way bash runs it closed much of that gap, and
the 34 harmful commands PAK still lets run are the next work, tracked in `docs/guard-benchmark.md`.
The same author wrote the cases and the rules, which favors PAK.

## The memory

`docs/memory-benchmark.md` compares PAK's memory with a baseline built from Hermes' documented
memory design (two bounded files injected whole, plus full-text search). On the held-out questions
PAK finds the right fact at rank 1 for 89 % of them, the baseline for 56 %; the baseline wins on
exact identifiers. It is a model of Hermes' design, not Hermes running.

## What this does not show

- No session of either agent ran with a real model. How each behaves when a model drives it, with
  the same model on both, is the remaining comparison, and it costs API credits.
- Hermes has far more surface than PAK (a TUI, a gateway to chat platforms, its own runtime). PAK
  does not try to match it there.
