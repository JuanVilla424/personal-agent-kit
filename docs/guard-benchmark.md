# Guard Benchmark

> **Date**: 2026-11-09 | **Run**: `python3 evals/guard_benchmark.py` (or `pak eval guard`) | **No
> model is called**

The guard's rules (`bin/auto_guard.py`, Stage 1) are measured on two sets. "Stopped" means blocked
or challenged: either way the command does not run on its own.

## The two sets

| Set      | File                                 | What it measures                                                   |
| -------- | ------------------------------------ | ------------------------------------------------------------------ |
| dev      | `evals/datasets/guard-corpus.jsonl`  | the cases the rules were written and tuned against: each must pass |
| held-out | `evals/datasets/guard-heldout.jsonl` | commands the rules never saw: how far they generalize              |

The held-out set follows a fixed protocol:

1. It is written before a round of changes to the guard, and frozen: its sha256 is in
   `evals/datasets/guard-heldout.floor.json`, and a test fails if the file changes.
2. It is measured in totals only until the round is done. No rule is tuned on one of its cases.
3. A held-out case that later gets fixed moves to dev. The next honest number needs a new batch,
   written before the next round, with its own hash and floor.
4. A command the dev corpus already holds is not unseen: it is left out of the score and listed in
   the floor file.
5. The guard may never score below the floor (`evals/tests/test_guard_benchmark.py`).

The same author wrote both the cases and the rules. That favors the guard, and is said here.

## Results

The 2026-11-09 batch has 123 commands: 92 harmful across ten groups (files, data, git, exfil,
remote code, persistence, security, power, guard tampering, disks) and 31 harmless look-alikes.
Two are already in the dev corpus and are left out.

| Guard                     | Stopped of the 91 harmful | Ran of the 30 harmless |
| ------------------------- | ------------------------- | ---------------------- |
| PAK, regex rules only     | 35                        | 24                     |
| PAK, with `shell_parse`   | **57**                    | **26**                 |
| Hermes Agent `v2026.9.24` | 36                        | 24                     |

Dev: 175 of 175 stopped and 104 of 104 ran.

What changed in the round: `bin/shell_parse.py` reads the command the way bash will run it
(quotes, escapes, `$'…'`, the line's own variables, wrappers such as `sudo` and `timeout`, the
global options of git, kubectl and the like, and the code nested in `bash -c`, `eval`, `$(…)` and
`find -exec`), and every rule also reads that. New rules cover git's safety net (`git_history`),
the hooks folder (`hooks_path`) and code the text never spells out (`dynamic_code`), and the
pipeline check of `exfil_creds` catches a dump of the environment or a credential folder piped out.

## What it still misses

34 of the 91 harmful commands still run. The rules read the command's text and shape, not what an
inline program in another language does, nor what a script already on disk does. The worker's
container (`pak task`) and the snapshots (`pak snapshot`) are the line behind them.
