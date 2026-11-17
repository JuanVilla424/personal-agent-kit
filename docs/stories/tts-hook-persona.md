# TTS hook for Claude Code (WSL2) + personality layer

**Origin**: party-mode (Mary/John/Winston/Sally/Murat), 2026-09-06. Full context of the
debate is in the session history — this doc is the actionable summary for tracking
progress, not the debate itself.

**Goal**: hear Claude Code's responses and permission requests as audio, with a voice that
has its own character (persona) instead of flat reading.

---

## Environment check (done, with Story A already implemented)

This box is WSL2 (confirmed via the kernel). WSLg exposes audio:

```
/mnt/wslg/PulseServer  → exists (socket, permissions 777)
PULSE_SERVER           → not set by default for user <user>
                          (tts_speak_worker.py sets it at runtime if missing and the socket exists)
```

`ffmpeg` and `pulseaudio-utils` installed (`sudo apt-get install ffmpeg pulseaudio-utils`).
`edge-tts` installed in `.venv` via `requirements.txt`.

**Real finding, not anticipated in the debate**: `ffplay` (SDL2 audio backend) hangs
indefinitely when playing against WSLg's PulseAudio-RDP sink — it doesn't honor
`-autoexit`. `paplay` (talks directly to PulseAudio) does play the full file in real
time. `audio_queue.py` tries `paplay` first, `ffplay` as a documented fallback for other
environments where it does work — with `timeout=` as a safety net either way.

---

## Closed decisions

1. Default engine v1: **edge-tts**. Piper documented as an offline fallback, not
   fully implemented in v1 (candidate for Story C if needed later).
2. Hook events v1: **Stop** and **Notification**. `SubagentStop` deferred (out of v1 scope).
3. Playback via `ffplay` or `paplay` over WSLg's `PulseServer`.
4. Engine interface: base class `TTSEngine.synthesize(text) -> Path`, one file per engine in
   `.claude/hooks/tts_engines/`, dictionary-based registration — never business-logic conditionals.
5. Persona rewriting (Story B) reuses the pattern already in this repo
   (`post-write-judge.sh` → `judge_against_agents.py`: `claude -p` + `PAK_HOOK_RUNNING=1` for
   anti-recursion) — it doesn't invent a new mechanism.
6. Persona rewrite timeout ~5s → automatic fallback to clean text. The hook
   **always** exits with code 0, no matter what.
7. Config (`TTS_ENGINE`, `TTS_PERSONA`, paid-engine keys) lives in the repo's root `.env` —
   no new hook-specific `.env` is created.
8. Permission messages and critical errors: the persona adjusts _only_ tone, content stays
   nearly literal. Summaries and transitions: full persona.
9. Long responses: simple character-limit truncation in v1 (no LLM-based summarization —
   one more LLM pass is more of a fidelity risk, exactly what the hard rule avoids).
10. Coordination between parallel Claude sessions (this box normally runs 3+): **deferred**,
    documented as a known risk, not resolved in v1 (see Risks).

## Known risks, not resolved in v1

- **Overlap between parallel sessions**: Story A's queue is _in-process_ — it doesn't
  coordinate across different Claude session processes running at the same time under the
  same user. With 3+ concurrent sessions (normal on this box), audio can overlap. Future
  mitigation: a simple system-level file lock — not implemented now.
- **edge-tts depends on an unofficial Microsoft endpoint** — no SLA, can break without
  notice. That's why the engine interface is swappable from day one.

---

## Story A — Working TTS hook, clean text, no persona

**Must work and be testable independently, without Story B.**

### Files to create

- `.claude/hooks/tts_hook.py` — hook entry point. Reads JSON from stdin
  (`hook_event_name`, `transcript_path`, `message`), extracts the text (parses the transcript for
  `Stop`, uses `message` directly for `Notification`), truncates if it exceeds the limit, queues
  synthesis+playback. Logging to a file (`logging`, never stdout). Always exits 0.
- `.claude/hooks/tts_engines/__init__.py` — registry `ENGINES = {"edge-tts": EdgeTTSEngine}`.
- `.claude/hooks/tts_engines/base.py` — abstract class `TTSEngine` with
  `synthesize(text: str) -> Path`.
- `.claude/hooks/tts_engines/edge_tts_engine.py` — implementation using the `edge-tts` library.
- `.claude/hooks/audio_queue.py` — non-blocking playback queue (so two consecutive messages
  don't overlap within the same process).
- `.env.example` (root) — adds `TTS_ENGINE=edge-tts` with a comment.
- `local/hooks/install-hooks.py` — register `tts_hook.py` on `Stop` and `Notification`.
- `local/hooks/README.md` — new row in the hooks table.

### Acceptance criteria (verifiable)

- [x] A real `Stop` event plays audio with the response's text (truncated if it exceeds
      the configured limit). Verified against this session's real transcript
      (10,966 characters → extracted, code block collapsed, truncated to 500 + "...continues").
- [x] A permission `Notification` event plays the request's text without altering paths
      or commands (no rewriting in A — the text is the original).
- [x] Two near-simultaneous events don't overlap — verified live: two
      `Notification`s fired in parallel synthesize at the same time (42ms apart) but
      play back serially (the second playback started ~6s after the first,
      exactly when it ended — timestamped log in the commit).
- [x] The hook exits 0 even if the player fails — degrades to silent, never breaks
      or blocks the session. **Real finding during testing**: `ffplay` hangs indefinitely
      against WSLg's PulseAudio-RDP sink (doesn't honor `-autoexit`) — confirmed with `ps` (process
      still alive minutes later) and by comparing with `paplay`, which does play the full audio
      in real time (real duration matches `ffprobe` exactly). Preference order changed to
      `paplay` first, `ffplay` as fallback — documented in `audio_queue.py`.
- [x] ` ```code``` ` blocks are detected and collapsed to a short phrase before synthesis,
      never read character by character.
- [x] Logging goes to a file; the hook's `stdout` stays clean (doesn't pollute the protocol).
- [x] `python3 -m py_compile` clean on all 6 Python files; docstrings on every
      function/class; PEP 8.

### Iteration 2 — feedback from real listening

The user listened to v1 live and reported 3 real problems, all 3 fixed and
re-verified with evidence (not just "should work"):

1. **Symbols read as words** ("asterisco Historia", "barra diagonal", "uve doble uve
   doble uve doble" for a URL — Spanish for "asterisk Story", "forward slash", "double-u
   double-u double-u") — `_clean_text` only stripped code blocks, no Markdown at all. Full
   cleanup added: bold/italics, `#` headers, bullets, quotes, horizontal rules, inline code,
   links (keeps the visible text, drops the URL), bare URLs (→ "a link"), and **tables**
   (`| a | b |` → "a, b" — found while testing with a real example from this session, where
   tables came through with literal pipes and dashes, just as robotic).
2. **Audio cutting off** — root cause found and confirmed with `ffprobe` vs. real playback
   time: `paplay` playing edge-tts's mp3 directly cut off ~1.5s from the end of a 9.6s clip
   (8.02s actually played out of 9.6s real — variable-bitrate mp3 mishandled by
   `paplay`'s/libsndfile's decoder). Converting to WAV with `ffmpeg` before playback fixes it:
   same clip, 9.97s real out of 9.6s (within the process's startup margin, no longer cut
   off). `EdgeTTSEngine.synthesize()` now returns WAV, never mp3.
3. **Never truncate, read everything faster instead of cutting** — `MAX_CHARS`/"...
   continues" was removed entirely. `EdgeTTSEngine` now progressively raises edge-tts's
   `rate` with text length (+0% up to 300 characters, +5% every 50 characters after, capped
   at +40% so it stays intelligible) — the full text is always read, faster if it's long,
   never cut off.

### Iteration 3 — two more real bugs, found while listening with Story B already active

1. **Fixed playback timeout cut off long responses** — `play_serialized()` had a fixed
   `timeout=60`; a 2310-character response at +40% rate generates over 100s of real
   audio. Real log: `playback timed out after 60s (paplay) — killed` — a long response's
   final question was never actually heard. Fixed: the timeout is now computed via
   `wave` (standard library, no new dependencies) from the file's real duration
   (`duration * 1.1 + 10s`, floor of 60s). Tested with a real 75s-of-silence WAV: it finished
   cleanly (`exit=0`) at 74.1s real, instead of being killed at 60s.
2. **"Asterisk asterisk" and paths read with "slash" even though they weren't in the
   visible text** — real root cause: text rewritten by the persona (Story B) was never
   passed back through Markdown cleanup before synthesis. The log showed the real case:
   `persona 'nova' rewrote 3207 -> 2732 chars for event Stop` — Haiku, while rewriting for
   style, could reintroduce `**bold**` that never existed in the original text (which is
   why the user never saw it), and those symbols reached edge-tts raw. Also, `_clean_text`
   (Story A) only handled full URLs (`http://...`), never bare file paths
   (`bin/install.sh`, `.claude/hooks/persona.md`) — those had ALWAYS been read letter by
   letter as "slash", even without a persona. Fixed with two changes:
   - Markdown cleanup extracted into a new shared module (`text_cleaning.py`,
     standard library only) — used both by `tts_hook.py` (original clean text) and by
     `persona_rewriter.py` (mandatory final pass over the rewritten text, after the
     critical-token check and never before — that check needs to see the literal slashes
     to be able to compare paths).
   - New path conversion: any token with at least one "/" (e.g.
     `.claude/hooks/persona.md`) has "/" → " slash " and "-" → " dash " applied within
     that same token — this is the requested convention ("we're in colombia: dash,
     slash" [user's own words, quoted], never "diagonal"/"barra"/"asterisco"). Standalone
     words with a dash and no slash (normal prose) are left untouched — explicitly tested.
   - Tested with a simulated rewrite that reintroduces `**bold**` and a path in backticks:
     the final text reaching the engine has no asterisks, no backticks, and no literal
     slashes. Also tested with a real rewrite (a real `claude -p` call, not simulated) of
     the Story B permission case with a path/flag/number — still passes the critical-token
     check and the final result humanizes the path correctly.

### Iteration 4 — Claude Code's own English-language messages ("Claude is waiting for...")

`Notification` events don't always carry text generated by Claude — Claude Code sends
some of its own messages (e.g. "Claude is waiting for your input") hardcoded in English
regardless of the user's configured language. New module `language_normalizer.py`,
same `claude -p` + `PAK_HOOK_RUNNING=1` pattern as `persona_rewriter.py`:

- Local heuristic first (Spanish-vs-English stopword bag, no cost or latency) —
  only calls the model when the text really seems to need translation. Claude's own
  responses (already in the target language) never trigger the extra call.
- `TTS_LANGUAGE=es` (new, in `.env`/`.env.example`) — target language configurable
  globally, not hardcoded. [Note, later in this session: the default was later changed to
  `en` — see `MODELS.md`'s "Output Language" section and the roadmap note there.]
- Always runs, BEFORE the (optional) persona step, and works the same with
  `TTS_PERSONA` empty — doesn't depend on a persona being active.
- Same critical-token check as the persona step (`preserves_critical_tokens`, now in the
  shared `text_cleaning.py`, no longer duplicated between the two modules).
- Tested for real: `ensure_language("Claude is waiting for your input")` →
  `"Claude está esperando tu entrada"`. Tested end-to-end with a real synthetic
  `Notification` event through the full hook — real log:
  `language normalized 32 -> 32 chars (target=es)` → `persona 'nova' rewrote 32 -> 38
chars` → normal synthesis and playback (`exit=0`).

### Iteration 5 — two real pronunciation issues, not Markdown-related

1. **"10/10" read as a path** — `PATH_RE` (Iteration 3) treated any
   `something/something` as a file path, including a numeric score like `10/10` (something
   this very hook says often: "black/pylint (10/10) clean"). Added
   `RATIO_RE` (`\d+/\d+` → "X out of Y"), running BEFORE `PATH_RE` so it claims
   purely numeric ratios first — a real path like `bin/install.sh`
   still goes to `PATH_RE` unchanged.
2. **English loanwords with a silent "h"** — in Spanish "h" is silent by default
   (correct in "hola", "hacer" — "hello", "to do"), but in English-borrowed technical terms like
   "hardcodeado"/"hackear" ("hardcoded"/"to hack") the "h" comes from the English aspirated
   sound, which in Spanish gets approximated with "j" (the same substitution Spanish speakers
   make when pronouncing them). Added `ANGLICISM_H_RE`, an explicit, narrow list
   (`hardcode\w*`, `hack\w*`) that rewrites the initial "h" as "j" — never a
   general "h" rule, which would break real Spanish words. Tested: "hola,
   hacer, hacerlo" stay untouched; "hardcodeado"/"Hardcodeado"/"hackear"/"hackeo"
   become "jardcodeado"/"Jardcodeado"/"jackear"/"jackeo" (initial capitalization
   preserved). List meant to grow if more cases get reported.

### Iteration 6 — "hackeado" sounded like "yaqueado", not "jaqueado"

The Iteration 5 fix (h→j) wasn't enough for the "hack" family: "jackeado"
still sounded wrong ("yakear", per the user), because Spanish doesn't have the
digraph "ck" — the /k/ sound before "e"/"i" is spelled "qu" (as in "jaqueca" — "migraine"),
never "c" or "ck". `ANGLICISM_H_RE` was split into two separate rules:

- `HARDCODE_RE`: logic unchanged, h→j only — its "c" is already followed by "o"
  (`code`), which already sounds correctly like /k/ in Spanish ("jardcodeado" is fine).
- `HACK_RE` (`hack` + a suffix starting with "e"): rewrites the whole "hack" as
  "jaqu", not just the "h" — "hackeado" → "jaqueado", "hackear" → "jaquear", "hackeo"
  → "jaqueo", "hackeando" → "jaqueando". This incidentally also covers "hacker"/"hackers"
  → "jaquer"/"jaquers" (same "hack" + vowel pattern), consistent even though not
  reported yet.

### Iteration 7 — "pylint" and an exceptions dictionary for non-conjugating names

"hardcode"/"hack" need prefix+suffix rules because they conjugate (as verbs). A
tool name like `pylint` doesn't conjugate — a per-word regex isn't worth it for this. Added
`PRONUNCIATION_OVERRIDES`, a simple whole-word → respelling dictionary, with a single
generic regex (`OVERRIDE_RE`) built from its keys. Adding a newly reported term in the
future is a one-line change, no new regex. First entry: `pylint` → `piyilint` (confirmed by
the user between two options he proposed himself, not guessed). Tested: "Pylint"
→ "Piyilint" (capitalization preserved), works together with `RATIO_RE`/`PATH_RE` in the
same sentence ("black/pylint (10/10) clean" → "black slash piyilint (10 out of 10)
clean").

### Status

- [x] **Complete and verified live** on this box (real WSL2, real audio via WSLg/PulseAudio),
      including Iteration 2 from real listening feedback.

---

## Story B — Personality layer on top of A

**Requires Story A working first.** Implemented on top of **edge-tts** (Chatterbox
was ruled out for CPU latency — see the section below).

### Files created

- `.claude/hooks/persona.md` — persona schema + the `nova` persona filled in.
- `.claude/hooks/persona_rewriter.py` — parses `persona.md`, builds the prompt with the
  active persona (`TTS_PERSONA`), invokes `claude -p` + `PAK_HOOK_RUNNING=1` (same pattern as
  `judge_against_agents.py`), applies a timeout, and falls back to clean text on any doubt.
- `tts_engines/base.py` and `tts_engines/edge_tts_engine.py` — `synthesize()` now accepts
  `rate: Optional[float]` (multiplier, 1.0 normal) and `pitch: Optional[int]` (Hz, 0
  normal); `None` for both reproduces Story A's exact behavior (automatic length-based
  rate, neutral pitch) — the persona is an optional override, not a replacement of A's
  pipeline.
- `tts_hook.py` — `PAK_HOOK_RUNNING` guard at the start of `main()` (a nested `claude -p`
  session from `persona_rewriter.py` must never re-trigger this same hook); the payload it
  builds for the worker changed from plain text to JSON `{"event": ..., "text": ...}` so the
  event type can be carried through to the rewrite step.
- `tts_speak_worker.py` — if `TTS_PERSONA` is set, calls `persona_rewriter.rewrite()`
  before synthesis and passes `rate`/`pitch` to the engine.
- `.env.example` and `.env` — `TTS_PERSONA=nova` (empty = no rewriting, clean text as-is,
  Story A's behavior).

### `persona.md` schema (persona `nova`, already filled in)

```markdown
## nova

name: Nova
language: es
tone: entusiasta, técnica, cercana
formality: informal (tuteo)
verbal_tics: ["dale", "mirá", "quedó"]
error_reaction: reconoce el error con calma, sin dramatizar, propone el siguiente paso
success_reaction: celebración breve, sin exagerar
rate: 1.05
pitch: 20
```

`pitch` corrected to Hz (the real unit used by `edge_tts.Communicate`, confirmed by reading
its source code) — the original design example said `+2%`, which isn't a valid pitch unit
in edge-tts (only `rate`/`volume` are percentages; `pitch` is always `±NHz`).

### Real correction to the original plan: `claude -p` timeout

Closed decision #6 estimated "~5s" for the rewrite. Measured on this box: a
`claude -p` call with Haiku, even with a trivial one-word prompt, takes **7.74s real**
(CLI/node startup dominates, not model latency) — with a 5s timeout, the
rewrite **always failed**, falling back to clean text 100% of the time, without
this being a visible bug (the fallback is silent by design). Raised to **45s** — the same
value `judge_against_agents.py` already uses for this same kind of call — with no impact on
the Claude Code session (all of this runs in the detached worker, never blocks).

### Acceptance criteria (verified with real evidence, not just "should work")

- [x] With `TTS_PERSONA=nova`, a normal summary message (`Stop` event) sounds with Nova's
      tone: `"Listo, actualice el archivo config/settings.yaml y el puerto quedo en 8080..."`
      → rewritten to `"Dale, corrí los tests y pasaron todos los 214 casos. Actualicé el
archivo config/settings.yaml y el puerto quedó en 8080."` — verbal tic added
      ("Dale"), `config/settings.yaml` and `8080`/`214` untouched.
- [x] A permission message (`Notification` event) with a path and a command —
      `"...eliminar el archivo /home/user/test.log con el comando rm -f y liberar 512 MB..."`
      — after Nova stayed **nearly literal**: it only added "Mirá," at the start;
      `/home/user/test.log`, `rm -f`, and `512` identical character for character (verified
      programmatically by comparing the set of critical tokens before/after, not by eye).
- [x] Mechanical check, not just the prompt: `_preserves_critical_tokens` was also tested
      with a simulated rewrite that DID drop `512` and a path — the function correctly
      returned `False`, confirming the fallback really triggers on an actual loss,
      not only in the trivial "nothing changed" case.
- [x] Real end-to-end run (synthetic `Stop` payload → `tts_hook.py` → detached worker →
      `persona_rewriter` → `edge-tts` → `paplay`), real log:
      `persona 'nova' rewrote 98 -> 94 chars for event Stop` →
      `edge-tts synthesized 94 chars at rate +5%, pitch +20Hz to ...` →
      `playback finished (paplay, exit=0)` — confirms the unit conversion
      (`rate: 1.05` → `"+5%"`, `pitch: 20` → `"+20Hz"`) and that the audio played
      in full, not just that the file was generated.
- [x] If `claude` isn't on PATH, the model doesn't respond in time, or the persona doesn't
      exist in `persona.md`, `rewrite()` returns the original text untouched — never an
      error, never silence (same path as Story A with no active persona).
- [x] `python3 -m py_compile` clean on the 2 new files + the 3 modified ones; `black`
      and `pylint` (10.00/10) with no findings.

### Status

- [x] **Complete and verified live** on this box (real WSL2, real `claude -p`, real audio
      via WSLg/PulseAudio) on top of edge-tts.

---

## Alternative engine investigated: Chatterbox (self-hosted) — not adopted, CPU latency

After listening to Story A live, the request shifted from "understandable" to "a more
human voice, customizable, with emotion, pauses, conversational — like ChatGPT, but with
nothing paid (no OpenAI, no ElevenLabs, no other paid AI)". Investigated edge-tts (already
in use, no real emotion control), Piper (offline but robotic), OpenAI/ElevenLabs/Hume/Cartesia
(ruled out for being paid), and **Chatterbox** (Resemble AI, MIT, self-hosted,
[devnen/Chatterbox-TTS-Server](https://github.com/devnen/Chatterbox-TTS-Server)) — the only
candidate meeting "free + own instance + real quality/expressiveness".

### What was done

- Submodule added at `local/scripts/chatterbox-tts-server` (per explicit request: "add it
  as a submodule if needed" [user's own words]).
- Image built and container started on this box via `docker-compose-cpu.yml`
  (`chatterbox-turbo`, `device: auto` → resolves to CPU on its own, no `config.yaml` edit
  needed; the compose file's `HF_TOKEN=YOUR_TOKEN_HERE` placeholder didn't need replacing —
  the model is public and downloaded without auth).
- Tested end-to-end for real, not just in theory: `POST /tts` returned a real WAV
  (24kHz mono), and that WAV played correctly through the same `paplay` + `PULSE_SERVER`
  WSLg path Story A already uses.

### Why it wasn't adopted

**Hard evidence, not an estimate**: a 228-character paragraph generated 16.04s of real
audio (`ffprobe`) but took **4m 3s** to synthesize — ~15x slower than real time. Verified
that it wasn't a misconfiguration: inside the container, `torch` was already using all 6
host cores (`torch.get_num_threads() == 6`, no cgroup/cpuset limit) — that's this
transformer model's real ceiling on this CPU, not something tunable with an env var. A
typical Claude response (several times longer than the test paragraph) would take
20-40+ minutes to hear, which contradicts the whole feature's conversational/responsive
purpose — and combined with the hard rule of never truncating (see Story A's Iteration 2),
messages would keep piling up with no way to shorten the wait.

Given the options (Chatterbox only on `Notification`, Chatterbox everywhere, make it
opt-in, or keep optimizing), the decision was: **edge-tts stays exactly as it was**
(Stop and Notification, unchanged) — "in that case edgetts would be better" [user's own
words].

### What did get confirmed, in case the hardware changes someday

- `chatterbox-turbo` natively supports paralinguistic tags in the input text — `[laugh]`,
  `[chuckle]`, `[sigh]`, `[gasp]`, `[cough]`, `[clear throat]`, `[sniff]`, `[groan]`, `[shush]`
  — these would cover Story B's "emotions/pauses" without an LLM rewrite or SSML.
- The `exaggeration` parameter (0.25–2.0, factory default 1.3) controls expressiveness per
  request — a direct, simple mapping to a future persona "emotion level".
- The native `POST /tts` endpoint (`CustomTTSRequest` in `models.py`) exposes `exaggeration`,
  `temperature`, `cfg_weight`, `speed_factor`, `language`, `seed` per request; the
  `/v1/audio/speech` endpoint (OpenAI-compatible) does NOT expose `exaggeration` per
  request — if this is revisited, always use the native endpoint.

### Submodule status (left as is, powered off)

- Container stopped and removed (`docker compose -f docker-compose-cpu.yml down`) — it
  doesn't run or consume CPU/RAM on this box.
- The Docker image (`chatterbox-tts-server-chatterbox-tts-server:latest`) and the named
  volume `chatterbox-tts-server_hf_cache` (model already downloaded, avoids re-downloading)
  **were kept**, in case this gets revisited later.
- It was **not** integrated into the hook: `tts_engines/chatterbox_engine.py` doesn't exist,
  `ENGINES`, `.env`, `.env.example`, and `requirements.txt` were untouched — `TTS_ENGINE`
  stays `edge-tts`.
- To pick this back up later (same box): `docker compose -f
local/scripts/chatterbox-tts-server/docker-compose-cpu.yml up -d` (reuses the image and the
  already-cached model, doesn't re-download or rebuild from scratch).

> **Update — Story C (see below):** this "paused" submodule is exactly
> what got picked back up as a **fallback** engine (never primary) for when `edge-tts` fails
> at runtime. The three bullets above (`chatterbox_engine.py` doesn't exist, `ENGINES`/
> `.env` untouched) no longer reflect the current state — they remain as a historical
> record of the original decision, not the current state.

---

## Story C — Chatterbox as edge-tts's offline fallback

**Not a primary engine** (the ~15x real-time latency on CPU, measured above, is still
real and hasn't changed). It's a **fallback**: only tried when `edge-tts` genuinely
fails at runtime (its unofficial, SLA-less endpoint is exactly the scenario this
covers) — slow-but-audible beats silence in that one case.

### Files created/modified

- `.claude/hooks/tts_engines/chatterbox_engine.py` (new) — `ChatterboxEngine`, calls the
  local server's native `POST /tts` (`localhost:8004`, `voice_mode: predefined`,
  `predefined_voice_id: Emily.wav`, `language: es`). `rate` maps directly to Chatterbox's
  `speed_factor`; `pitch` is accepted for interface parity but has no effect (Chatterbox's
  API has no pitch control). 600s timeout — deliberately generous, given the ~15x measured
  above; runs in the detached worker, never blocks the Claude Code session.
- `tts_engines/__init__.py` — `ENGINES["chatterbox"] = ChatterboxEngine`.
- `tts_speak_worker.py` — new function `_synthesize(text, rate, pitch)`, split out of
  `main()` so it can be tested on its own: tries `TTS_ENGINE`, and only if that
  `.synthesize()` raises an exception does it try `TTS_FALLBACK_ENGINE` (if configured and
  different from the primary) — with no fallback configured, behavior is identical to
  before Story C (the exception still propagates up to `main()`'s `except`, which swallows
  it and exits 0).
- `requirements.txt` — added `requests` (already transitively available in the
  `.venv`, but undeclared — fixed so this repo declares its own deps).
- `.env.example` and `.env` — `TTS_FALLBACK_ENGINE=chatterbox`.
- `bin/install.sh` — new step `[5/11]` "Local TTS (Chatterbox — offline fallback)": brings
  up the container (`docker compose -f docker-compose-cpu.yml up -d`) if Docker is
  available; unlike Qdrant/memory_service, this **never fails the installer** if Docker
  isn't there or the container doesn't start — it's a fallback, not a requirement
  (`v_chatterbox` isn't part of the final summary's hard-failure condition). All later
  steps were renumbered from `/10` to `/11`. Verification added against
  `GET /api/model-info` (lightweight, doesn't generate audio).
- **OpenCode: unchanged, on purpose.** The whole feature (Story A/B/C) lives in Claude
  Code's hook system (`Stop`/`Notification`/`PreToolUse`), which OpenCode doesn't have at
  all — there's no equivalent to mirror this into, unlike the plugins/LSP work (that one
  did share real infrastructure with OpenCode: the binaries and their config).

### Acceptance criteria (verified with real evidence)

- [x] `ChatterboxEngine.synthesize()` tested standalone against the real local server: it
      produced a valid WAV (`ffprobe`: 2.95s) honoring `rate=1.1` → `speed_factor=1.1`.
- [x] Fallback mechanism tested against the real `_synthesize()` function (not a parallel
      reimplementation): with a simulated primary engine that raises
      `RuntimeError` (representing a real edge-tts network failure) and
      `TTS_FALLBACK_ENGINE=chatterbox`, `_synthesize()` correctly falls back and
      returns a real Chatterbox WAV (122,924 bytes).
- [x] With no fallback configured (`TTS_FALLBACK_ENGINE=""`), the same simulated failure
      propagates uncaught — confirming pre-Story-C behavior stays intact
      when no fallback is configured.
- [x] `python3 -m py_compile`, `black`, and `pylint` (10.00/10) clean on the 3
      new/modified files.
- [x] `bash -n bin/install.sh` clean after the full renumbering of the 11 steps.

### Status

- [x] **Complete and verified** (real local tests against the container and against the
      real `_synthesize()` function). Only pending a real live end-to-end test with a
      _real_ (not simulated) edge-tts failure — not forced on purpose since it would
      require actually cutting network access, and the mechanism has already been tested
      against the real code.

---

## Story D — Uncommitted local persona + one voice per BMAD agent

Requested by the user after using Story B/C: to be able to have his own personal persona
without it landing in the repo, and to have each BMAD agent (party-mode) sound with a
distinct voice.

### Files created/modified

- `.claude/hooks/persona.local.md` (new, gitignored — added to `.gitignore`): same
  format as `persona.md`. `persona_rewriter._load_persona()` checks it FIRST — it can
  fully redefine an id that already exists in the shared file (personal override) or
  add a new one that only exists on that box. Left pre-populated with an editable copy of
  `nova` ready to customize.
- `persona.md`: new `voice` field (an `edge-tts --list-voices` voice name;
  `Persona`/`RewriteResult` gain the field, threaded the same way as `rate`/`pitch`) — Nova
  now declares her voice explicitly (`es-ES-AlvaroNeural`, the one she already had as the
  engine's default). New personas added, one per BMAD agent with a real
  `**Name**`/`**Icon**` in `.bmad/local/*.txt` — tone and reactions taken from each
  file's "Communication Style"/"Principles" section, not invented (e.g. an agent with a
  "no fluff, no disclaimers, just the verdict" principle ends up with no filler words and a
  fast rate; one with "calm under fire" ends up with a slower rate). Each with a distinct
  `edge-tts` voice, chosen only so they're clearly distinguishable from each other and
  from Nova.
- `persona_rewriter.py`: new function `detect_agent_persona(text)` — looks for
  party-mode's own format ("**Kai**: ...", documented in
  `.bmad/core/workflows/party-mode/steps/step-02-discussion-orchestration.md`, line
  76). Runs on text ALREADY cleaned by `clean_for_speech()`, which leaves "Kai:" in
  plain text (the `**` already stripped) — no need to detect raw markdown. The
  detected agent wins over `TTS_PERSONA`; if none is detected,
  `TTS_PERSONA` is used exactly as before (behavior outside party-mode is unchanged).
- `tts_speak_worker.py`: calls `detect_agent_persona()` before resolving the
  `persona_id`; `_synthesize()` and both engines (`EdgeTTSEngine`, `ChatterboxEngine`,
  base `TTSEngine`) gain the `voice` parameter (Chatterbox accepts and ignores it, same as
  it already does with `pitch` — its voices are its own files, not edge-tts names).
- Along the way, updated `.bmad/core/workflows/party-mode/steps/step-02-discussion-orchestration.md`
  line 78 (stale: it said "No TTS in this project... `.claude/hooks/bmad-speak.sh` doesn't
  exist" — true when it was written, no longer true).

### Acceptance criteria (verified with real evidence)

- [x] All 9 personas (`nova` + 8 agents) load fine, each with its own
      `voice`/`rate`/`pitch` — tested by reading all 9 directly.
- [x] Local override actually tested, not assumed: `rate` was changed to `1.99` ONLY in
      `persona.local.md`, and it was confirmed that `_load_persona("nova")` returned
      `1.99` (not the shared file's `1.05`), then reverted to the real value.
- [x] Agent detection tested with 4 cases: 3 real agents detected
      correctly, and a normal piece of Claude text with no agent correctly NOT
      detected (uses `TTS_PERSONA` in that case).
- [x] Real end-to-end: a synthetic `Stop` event with a real agent's party-mode format
      (`"**Name**: ..."`) through the full hook — real log with the
      format `persona '<id>' rewrote N -> M chars for event Stop (voice=<voice>)` →
      synthesis with that voice → successful playback (`paplay`, exit=0). Confirms that
      the detected agent's voice is used, not Nova's/`TTS_PERSONA`'s.
- [x] `python3 -m py_compile`, `black`, `pylint` (10.00/10) clean on the 6
      new/modified files.

### Iteration 2 — the persona's `rate` now combines with the auto-adjustment instead of replacing it

The previous round left this as an unfixed observation: with an active persona,
its `rate` ALWAYS won over `EdgeTTSEngine`'s length-based speed auto-adjustment for
long text (up to +40% in Story A) — a very long response with, say, a
slow-rate persona (-5%) wouldn't speed up the way it would with no persona. At the
user's request ("combine them" [user's own words]), this was fixed:

- `edge_tts_engine.py`: `_rate_for_length`/`_rate_to_percent_string` (computed
  separately, one overriding the other) were replaced by `_length_ramp_percent`
  (the pure length-based ramp) and `_rate_percent` (persona + ramp, summed, capped at
  `MAX_RATE_PERCENT`). With no persona (`rate=None`) the result is identical to before —
  base behavior was untouched.
- The result is additive, not a replacement: a -5%-rate persona with a very
  long response (ramp +40%) ends up at +35% — slower than neutral, but no longer stuck at
  -5% for a giant response. A +8%-rate persona with the same long response
  ends up capped at +40% just like everyone else, not at +48%.
- Tested with 6 real cases: no persona (short and long, same as before), a
  neutral persona with short text (just its baseline), a slow persona with long text (+35%,
  neither the isolated -5% nor the isolated +40%), a fast persona with long text (capped at
  +40%), and a slow persona with short text (-5%, no artificial floor — negative is
  valid).

### Status

- [x] **Complete and verified live** (real local persona, real agent detection,
      real end-to-end with the detected agent's voice, rate combination tested
      with 6 real cases).
