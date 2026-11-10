# Memory Benchmark

> **Date**: 2026-11-08 | **Command**: `python3 evals/memory_benchmark.py` | **Runtime**: 17 s, no
> model calls

`evals/memory_benchmark.py` measures how often the memory hands an agent the right fact. It runs
the real `memory_service` through its HTTP API, on an in-memory Qdrant with the same local
embedding model, against a baseline built from Hermes Agent's documented memory.

## Dataset

`evals/datasets/memory-recall.jsonl` is a fictional owner, public and synthetic:

- 59 memories, 21 of them versions of 10 facts that change over time (a laptop, a standup time)
- 354 ordinary notes written in between, seeded so every run is the same: a store in use
- 54 questions in four kinds: an exact identifier (`What is bramble?`), a paraphrase with no shared
  words (`When do I collect my kid after class?`), the current value of a changed fact, and a
  question in the other language (English and Spanish)

A question counts as found at rank r when its memory is r-th and no outdated version of the same
fact ranks above it: an agent that reads the old value first answers with it.

## Systems

| System      | What it is                                                                                                                                                   |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| pak         | The shipped `memory_service`: dense plus BM25 search, fused, and replacement by `state_key`                                                                  |
| pak-dense   | The first version: dense search only, no replacement                                                                                                         |
| bm25        | Lexical search only                                                                                                                                          |
| hermes-like | Hermes' documented memory: `MEMORY.md` (2,200 chars) and `USER.md` (1,375 chars) injected whole, newest first, plus FTS5 search over everything ever written |

The baseline is generous to Hermes on purpose: a memory inside the injected files counts as rank 1,
the files hold only the newest version of each fact, and FTS5 gets Porter stemming and accent
folding, which it does not do by default.

## Results

The fusion setting was chosen on the 27 dev questions (convex fusion, 0.7 on the dense side) and
is the service's default. The 27 test questions were not used to choose anything.

**Test questions:**

| System      | hit@1     | hit@5     | MRR@5     |
| ----------- | --------- | --------- | --------- |
| pak         | **0.889** | **0.926** | **0.901** |
| hermes-like | 0.556     | 0.667     | 0.602     |
| pak-dense   | 0.741     | 0.778     | 0.759     |
| bm25        | 0.333     | 0.407     | 0.364     |

**All 54 questions, by kind (hit@1 / hit@5):**

| Kind             | pak         | hermes-like | pak-dense   | bm25        |
| ---------------- | ----------- | ----------- | ----------- | ----------- |
| Exact identifier | 0.81 / 0.88 | 0.94 / 1.00 | 0.81 / 0.81 | 1.00 / 1.00 |
| Paraphrase       | 0.69 / 0.81 | 0.56 / 0.62 | 0.69 / 0.88 | 0.06 / 0.19 |
| Changed fact     | 1.00 / 1.00 | 0.80 / 0.80 | 0.10 / 0.10 | 0.00 / 0.00 |
| Other language   | 0.92 / 1.00 | 0.42 / 0.50 | 0.92 / 1.00 | 0.17 / 0.25 |
| **All**          | 0.83 / 0.91 | 0.69 / 0.74 | 0.67 / 0.74 | 0.35 / 0.41 |

## What it shows

- PAK finds the right fact more often than the Hermes-like baseline overall, and on paraphrases,
  changed facts and questions in the other language.
- **Hermes-like wins on exact identifiers**: its FTS5 finds a hostname or a number at rank 1 more
  often (0.94 against 0.81). A lower dense weight closes that gap (1.00 at 0.5) but loses
  paraphrases and the other language, so the dev split kept 0.7. An adaptive setting that leans on
  words when the question names something rare (`MEMORY_FUSION=adaptive`) also reaches 1.00 on
  identifiers, and lost on dev for the same reason (0.704 against 0.778 at hit@1): it stays an
  option, not the default.
- Replacement is what fixes changed facts: the first version, without it, answered 1 of 10.

## Limits

- The dataset is small (54 questions) and written for this benchmark: a difference of one question
  moves a test score by 0.037.
- The baseline approximates Hermes' documented design; it is not Hermes. Its agent decides what to
  keep in the files, and an LLM reads the results; here the files keep the newest entries and the
  score is the rank. The comparison against the real Hermes, with the same model, is Phase 4.
- The first run had a bug that this benchmark found: the only BM25 hit of a rare identifier got no
  lexical credit. It was fixed before these numbers.

## How to reproduce it

```bash
python3 evals/memory_benchmark.py            # writes temp/memory-benchmark/result.json
```

It needs the repo's `.venv` and the embedding model, which the first run downloads into
`local/scripts/memory_index/.cache/fastembed`.
