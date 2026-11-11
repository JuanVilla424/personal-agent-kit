# 🤖 MODELS.md — model capacity, cost, and quality for the agent

> What it costs to load/run this agent (EVERYTHING: harness + persona + protocols + bmad + memory +
> operational), **which models can handle it** (and with which protocol variant), and **which
> runs it best**. Regenerable: §1 with `bin/measure-footprint.sh`, §2 (benchmark) with
> `bin/benchmark-models.sh`. The model→variant wiring lives in `configs/model-protocol-map.yaml`.
>
> Tokens measured with **tiktoken `cl100k_base`** (real BPE, via `bin/count_tokens.py`) — a close
> proxy for Claude (~±10%); exact-Claude counts require the `count_tokens` API (needs a key, not
> available here).

## 📚 Table of Contents

- [1. Agent Footprint](#-1-agent-footprint--by-layer-token-map)
- [2. Models](#-2-models--capacity-and-benchmark)
- [Output Language](#-output-language)
- [3. Defaults by Scenario](#-3-defaults-by-scenario)
- [Findings & Roadmap](#️-findings--roadmap)
- [License](#-license)

---

## 📊 1. Agent footprint — by layer (token map)

The agent is NOT just persona+protocols. What consumes tokens, by layer:

| Layer                                                 | Component                                                                                         | ≈ tokens             |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------- |
| **1. Harness** (Claude Code CLI, outside the repo)    | base system prompt + built-in tool defs                                                           | ~10-20k (estimated)  |
|                                                       | MCP servers (`CLAUDE_MCP_CONFIG`: context7…)                                                      | variable (estimated) |
| **2. Resident** (always; `--add-dir` + session-start) | manifest roster (3.5k) / or one forced persona (~12k)                                             | 3.5-12k              |
|                                                       | `AGENTS.md` (3.8k) + `CLAUDE.md` (6.0k)                                                           | 9.8k                 |
|                                                       | `MEMORY.md` (KG index)                                                                            | 12.7k                |
|                                                       | **→ typical resident**                                                                            | **~26k**             |
| **3. On-demand** (per task)                           | enforcement 2.8k · protocols **full 23k / compact 5.7k / ultra 4.2k**                             | 6-26k                |
|                                                       | TROUBLESHOOTING 3.6k · README 2.4k · bmad commands 8.8k                                           | depends on task      |
| **4. BMAD — agents USED**                             | **bmm/agents 11.6k** (party-mode team: analyst, architect, dev…) — roster ~3.5k at runtime        | ~11.6k used          |
| **4b. BMAD — the rest (NOT loaded daily)**            | rest of bmm 621k (workflows/testarch/dev) · bmb 173k · core 38k · cis 28k · \_cfg 39k · local 30k | dead weight on disk  |
| **5. Knowledge** (RAG/recall)                         | lessons KB 8.7k (top-K) · memory KG **103k** (160 files) · agent_memory Qdrant                    | variable             |
| **6. Operational**                                    | pull/push (hook dance + pipeline), tool outputs, conversation                                     | grows                |

- **RESIDENT per task** ≈ **~26k** — what loads no matter what (what matters for model capacity).
- **RELEVANT UNIVERSE** (what COULD load, excluding the rest of bmm) ≈ **~466k**.
- **Total on disk** ≈ ~1.09M, but **~621k is the rest of bmm** (workflows/testarch/dev) that
  **NEVER loads** in daily use → dead weight on disk, doesn't count toward the real footprint.
- Why this matters: (a) **selective loading** (only what the task needs), and (b) the **protocol
  variant** (compact saves ~17k vs full).

> 🔎 **compact ≠ ultra (not a size scale):** `compact` = **lightweight** condensed version
> (~5.7k, for budget); `ultra` = **strict enforcement** variant (~4.2k, more rules, NOT the
> smallest one). For low-window models, the lightweight one is **compact**.

---

## 🧠 2. Models — capacity and benchmark

The resident weight is **~26k** (§1) and a comfortable session runs **80-150k** with `full`
protocols. All tested models have a **200k–1M** window (source: models.dev) → **all of them run
the agent with `full`, comfortably**. The `compact` variant (~3.8k) would only be needed for a
model with <64k window — none listed here.

> **Measured on the previous generation.** These results predate Fable 5.1, Opus 5.5, Sonnet 5.5
> and Haiku 5.5, which `bin/benchmark-models.sh` now targets. They have not been re-run: they are
> history, not a verdict on the current models.

Benchmark (Opus/Haiku/GLM/free-tier/etc. run 2026-06-21; Sonnet re-evaluated 2026-07-01 after
the Sonnet 5 upgrade): a representative task (recommend action on an oversized PROD server),
judged by Opus against a rubric (technical correctness, **natural output-language quality**, ID
redaction, conciseness). `out≈` = output tokens (bytes/4). The score separates "fits in the
window" from "runs it WELL". Expandable to more tasks with `bin/benchmark-models.sh`.

| Model             | Window | Variant | Latency | out≈ | **Score /10** | Note                          |
| ----------------- | ------ | ------- | ------- | ---- | ------------- | ----------------------------- |
| Opus 4.8          | 1M     | full    | 56s     | 718  | **9**         | Anthropic                     |
| Sonnet 5          | 1M     | full    | 56s     | 437  | **9**         | Anthropic                     |
| Fable 5           | —      | full    | 71s     | 652  | **9**         | Anthropic (Fable Mythos)      |
| Haiku 4.5         | 200k   | full    | 16s     | 357  | **8**         | Anthropic                     |
| Extended          | 1M     | full    | 160s    | 767  | **8**         | Custom provider (self-hosted) |
| GLM-5.2           | 1M     | full    | 48s     | 1139 | 7             | z.ai (opencode)               |
| DeepSeek-v4-flash | 1M     | full    | 18s     | 562  | 7             | opencode, free                |
| MiMo-v2.5         | 256k   | full    | 24s     | 795  | 6             | opencode, free                |
| Big-pickle        | 200k   | full    | 28s     | 666  | 6             | opencode, free                |
| Standard          | n/d    | full    | 22s     | 966  | 6             | Custom provider (self-hosted) |
| North-mini-code   | 256k   | full    | 42s     | 556  | 5             | opencode, free                |
| Nemotron-3-ultra  | 1M     | full    | —       | —    | n/a           | opencode, free; no response   |

> Re-run: `bash bin/benchmark-models.sh` (caches in `temp/benchmark/`; delete a `.out` to retry
> that model). GLM (zai) auto-loads its `ZAI_API_KEY` from `.bashrc`. `out≈` = tiktoken
> `cl100k_base`; `tok in`/cost aren't listed (exact-Claude counts require the `count_tokens` API).
>
> **Nested runs:** `claude -p --model <id>` invoked NESTED from an interactive session already
> running that same model deadlocked on Sonnet 5 (shared session/credential lock under
> `~/.claude`). Run `bash bin/benchmark-models.sh` from a terminal that is not an active Claude
> Code session on the model under test.

---

## 🌐 Output Language

The agent's **output** — reports (Iris), Slack bot replies, diagnostics, and messages —
defaults to **English**, matching the repo-wide default (`TTS_LANGUAGE=en` in `.env`,
`core/i18n.py`'s `locale="en"` default). It's fully configurable per deployment or per user:
change `TTS_LANGUAGE`, or pass an explicit `locale` where the bot calls `t()`/`detect_locale()`.
**Code, comments, and identifiers** always stay in **English** (repo rule, independent of the
output-language setting) — see [i18n note in the roadmap](#️-findings--roadmap) below.

Implication for model choice: natural quality in the configured output language is a criterion
and factors into the `score` (§2) above. A model that fits the window but writes poor or stilted
prose in that language doesn't cut it for the Slack bot. The benchmark table above specifically
judged **Spanish** output quality (from when Spanish was the repo default, 2026-06-21/07-01) —
re-running it to also score English output quality is open work now that English is the default
(see roadmap below).

---

## 🎯 3. Defaults by scenario

The defaults use the current generation. §2 does not measure them yet, so these are configured
defaults, not benchmark winners.

- **Slack bot**: `claude-sonnet-5-5` (`CLAUDE_MODEL`), with `claude-haiku-5-5` as fallback.
- **Quick tasks and per-write hooks**: `claude-haiku-5-5`.
- **Free / fallback**: DeepSeek-v4-flash (free, 18s, score 7 in §2).
- **opencode / codegen**: GLM-5.2 (score 7) or DeepSeek-v4-flash (free, score 7).
- **Small context** (<64k): `compact` + a model that fits; <32k → not viable.

---

## 🛣️ Findings & Roadmap

- ✅ **`session-start.sh` fixed**: loads `.bmad/local/orientation.txt` (previously the
  nonexistent `.ai/team-fullstack.txt` → the agent started with no context). This was the
  **root cause of the original problem**. Also, the agent's own config
  (`.claude/{hooks,agents,skills,scripts}`) now **travels with the repo** (previously gitignored).
- ✅ **Loader wired up for the Slack bot**: it injects the protocol variant based on the model
  (`model-protocol-map.yaml`). Interactive sessions always load `full`.
- 📦 **bmad**: the **agents** (~11.6k) ARE used (party-mode team); the **rest** (~621k:
  workflows/testarch/dev) does NOT load in daily use → dead weight on disk, outside the real
  footprint. Removing it is **optional** cleanup (it would break the
  `/bmad:bmm:workflows:*` commands).
- 🧠 **Memory KG = ~103k** (160 files) + `MEMORY.md` ~13k resident: the heavy component of the
  knowledge layer.
- 🔁 **Benchmark pending for the current generation**: §2 holds the 2026-06/07 results.
  Expandable with more tasks via `bin/benchmark-models.sh`.
- ✅ **`compact` variants** of the new protocols created
  (`protocols/compact/{repo-workflow,memory-protocol}.md`) → compact is now ~5.7k.
- ✅ **Real tokenizer implemented**: `tiktoken cl100k_base` via `bin/count_tokens.py` (dep in
  `requirements.dev.txt`); `measure-footprint` and the benchmark no longer use `bytes/4`. It's a
  close proxy for Claude (~±10%); exact-Claude counts require the `count_tokens` API (needs a key,
  not available here).
- 🌐 **i18n default flipped to English** (this session): `core/i18n.py`'s `t()`/`detect_locale()`
  and `TTS_LANGUAGE` used to default to Spanish (a leftover from this tool's original,
  single-team deployment) — now they default to English so the kit works out of the box for
  anyone, with Spanish (or any other locale added to `i18n.py`'s `_STRINGS` dict) fully available
  as an opt-in. The same default-Spanish pattern turned out to be duplicated in several other
  places that don't read `i18n.py` at all — `language_normalizer.py`'s own
  `DEFAULT_TARGET_LANGUAGE`, 9 independent `locale` parameter defaults across the Slack bot
  (`bot.py`, `ui/slash_commands.py`, `security/permissions.py`, `core/party_mode_prompt.py`,
  `core/progress.py`), and the TTS voice/respelling layer (`EdgeTTSEngine`'s and
  `persona_rewriter.py`'s `DEFAULT_VOICE`, `ChatterboxEngine`'s `DEFAULT_LANGUAGE`, the `nova`
  persona's own `voice` field, and `text_cleaning.py`'s Spanish-only phonetic respellings for
  `hardcode`/`hack`/path separators, which used to run unconditionally instead of only under
  `TTS_LANGUAGE=es`) — all found by reading the actual code paths, not by grepping for Spanish
  prose, since the code itself was already in English and only the _value_ defaulted wrong.
  All now default to English. Open follow-up: the §2 benchmark still only scores Spanish output
  quality; an English-quality pass is pending. A deeper, agent-level i18n story — the 4 named
  BMAD personas (Kai/Raven/Elena/Iris) actually responding in the user's configured language,
  rather than keeping their Spanish-authored tone/verbal_tics/voice as fixed character design —
  is future work, not yet started.

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file
included in this repository.
