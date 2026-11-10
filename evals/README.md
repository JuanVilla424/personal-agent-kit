# 🧪 Agent evals — quality gate

![Type](https://img.shields.io/badge/Type-Eval%20suite-blue.svg)
![Gate](https://img.shields.io/badge/Gate-pass--rate-green.svg)

**Agent evaluation** suite (not code): runs representative tasks through the real agent
and **scores its behavior** against deterministic assertions + a rubric. It complements
the model benchmark (`bin/benchmark-models.sh`, see `MODELS.md §2`): the benchmark measures
_which model_ is better; these evals measure _whether the agent follows its rules_ (redaction,
approval, output language, no-hallucination, no-prompt-leak) and **gate** on a quality drop.

## 🚀 Usage

```bash
# pre-release, local (needs claude reachable):
.venv/bin/python evals/run_evals.py --model sonnet --threshold 0.8
# exit code != 0 if pass-rate < threshold  → works as a gate
```

Variables: `EVAL_MODEL`, `EVAL_THRESHOLD`. Dataset: `--dataset` (default `datasets/core-behavior.jsonl`).

## 🗂️ Dataset

One JSON per line in `datasets/*.jsonl`:

```json
{
  "id": "...",
  "prompt": "...",
  "asserts": { "must_include": ["regex"], "must_not_include": ["regex"] },
  "rubric": "..."
}
```

- `must_include` / `must_not_include`: deterministic regex (the gate relies on these).
- `inject_secret: true`: the runner injects a **fake** AWS key (assembled from parts in `run_evals.py`
  so it doesn't trip the pre-write secret-guard) and verifies the agent **does not repeat it**.
- `rubric`: criterion for an LLM judge (future use; today the gate runs on assertions only).
- System-prompt leak: `SYS` carries a `SYS-DO-NOT-REVEAL-*` sentinel; if it shows up in the
  output, the agent leaked its prompt.

## 🔌 CI

The **logic tests** (`tests/test_run_evals.py`: `check_asserts`, `gate`, dataset validity)
run in CI with pytest — **no** model needed. The **behavior gate** (`run_evals.py`) needs a
reachable model: today CI has no key, so it runs **locally pre-release** or as a
**manual/scheduled** job with `EVAL_MODEL` + the matching key. Once CI has a key, add an
`agent-eval` job that runs `run_evals.py` and inherits its exit code as the gate.
