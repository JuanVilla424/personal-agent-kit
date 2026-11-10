---
description: Turns voice (TTS) on or off by toggling TTS_ENABLED in .env
---

Change `TTS_ENABLED` in `.env` based on $ARGUMENTS (if any). Never read or print the rest
of `.env` — only that key, via `dotenv`, never `cat`/`grep`/reading the file directly.

- $ARGUMENTS contains `off` → set `TTS_ENABLED=false`
- $ARGUMENTS contains `on` → set `TTS_ENABLED=true`
- No $ARGUMENTS → read the current value (default `false` if the key doesn't exist) and flip it

Command (adjust `NEW_VALUE` to `true` or `false` per the case above; for the "no
arguments" case, first resolve the current value with `dotenv_values('.env').get('TTS_ENABLED',
'false')` and flip it):

```bash
.venv/bin/python3 -c "from dotenv import set_key; set_key('.env', 'TTS_ENABLED', 'NEW_VALUE')"
```

No need to restart OpenCode — the check runs on every response, inside the shared
worker (`.claude/hooks/tts_speak_worker.py`, invoked by `session-lifecycle.js`), before
synthesizing anything.

Report to the user in a single line: "TTS off" or "TTS on", matching the resulting value.
