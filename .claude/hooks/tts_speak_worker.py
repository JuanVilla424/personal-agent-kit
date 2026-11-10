#!/usr/bin/env python3
"""Background worker for the Claude Code TTS hook.

Reads text on stdin, synthesizes it with the configured TTS engine, then plays it
back through ``audio_queue.play_serialized`` so two messages in a row never
overlap. Spawned detached by ``tts_hook.py``, which does not wait for it to finish.
Never raises past ``main()`` and always exits 0 — a failure here must never surface
to the Claude Code session that triggered it.

Run with the project's ``.venv`` interpreter (needs ``edge-tts`` and
``python-dotenv``); ``tts_hook.py`` invokes it that way explicitly.
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
LOG_FILE = REPO_ROOT / "temp" / "logs" / "hooks" / "tts_hook.log"
PULSE_SOCKET = Path("/mnt/wslg/PulseServer")
DEFAULT_ENGINE = "edge-tts"

sys.path.insert(0, str(HERE))
from audio_queue import play_serialized  # noqa: E402
from tts_engines import ENGINES  # noqa: E402
import language_normalizer  # noqa: E402
import persona_rewriter  # noqa: E402


def _setup_logging() -> None:
    """Configure file-only logging, matching ``tts_hook.py``'s setup."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _ensure_pulse_server() -> None:
    """Default ``PULSE_SERVER`` to WSLg's socket if unset and the socket exists.

    WSLg does not export ``PULSE_SERVER`` system-wide for every Linux user — only
    the interactive user it configures gets it via their session environment.
    Setting it here (rather than relying on ``~/.bashrc``, which hooks do not
    source) works regardless of which user or how Claude Code invokes this hook.
    """
    if "PULSE_SERVER" not in os.environ and PULSE_SOCKET.exists():
        os.environ["PULSE_SERVER"] = f"unix:{PULSE_SOCKET}"


def _synthesize(
    text: str, rate: Optional[float], pitch: Optional[int], voice: Optional[str]
) -> Path:
    """Synthesize with the configured engine, falling back on outright failure.

    ``TTS_FALLBACK_ENGINE`` (Historia C, optional) is tried only if the primary
    engine's ``synthesize()`` raises — e.g. edge-tts's unofficial endpoint being
    unreachable. Chatterbox (self-hosted, no network needed) is the intended
    fallback: slow on CPU (see docs/stories/tts-hook-persona.md), but slow-but-
    audible beats silent in that one specific case. This is never the common path
    when the primary engine is healthy — no fallback is attempted otherwise.

    Args:
        text: The text to synthesize (already clean, possibly persona-rewritten).
        rate: Optional speed multiplier, forwarded to whichever engine runs.
        pitch: Optional pitch shift in Hz, forwarded to whichever engine runs.
        voice: Optional engine-specific voice identifier, forwarded to whichever
            engine runs (e.g. a BMAD agent's own voice in party-mode).

    Returns:
        Path to the synthesized audio file.

    Raises:
        Exception: If the primary engine fails and no usable fallback is
            configured (unset, unknown, or same as the primary), or the
            fallback itself also fails.
    """
    engine_name = os.getenv("TTS_ENGINE", DEFAULT_ENGINE)
    fallback_name = os.getenv("TTS_FALLBACK_ENGINE", "")
    engine_cls = ENGINES.get(engine_name, ENGINES[DEFAULT_ENGINE])
    try:
        return engine_cls().synthesize(text, rate=rate, pitch=pitch, voice=voice)
    except Exception:
        fallback_cls = ENGINES.get(fallback_name) if fallback_name else None
        if not fallback_cls or fallback_name == engine_name:
            raise
        logging.exception(
            "engine '%s' failed — retrying with fallback '%s'",
            engine_name,
            fallback_name,
        )
        audio_path = fallback_cls().synthesize(
            text, rate=rate, pitch=pitch, voice=voice
        )
        logging.info("fallback engine '%s' succeeded", fallback_name)
        return audio_path


def main() -> int:
    """Worker entry point: synthesize the text read from stdin and play it back.

    Reads a ``{"event": ..., "text": ...}`` JSON payload from stdin (written by
    ``tts_hook.py``). The text is first passed through ``language_normalizer``
    (unconditional — covers Claude Code's own built-in Notification strings, which
    are hardcoded in English regardless of the user's language). It's then rewritten
    in a persona's voice — the BMAD agent detected in the text (party-mode,
    ``persona_rewriter.detect_agent_persona``) wins over the ``TTS_PERSONA``-
    configured default; when neither applies (no agent detected AND ``TTS_PERSONA``
    unset/empty), no rewrite happens at all, exactly Historia A's original behavior.
    Every step falls back to its input unchanged on any doubt, so a broken language/
    persona layer degrades to silence-free plain speech, never to an error.

    Returns:
        Always 0.
    """
    _setup_logging()
    load_dotenv(REPO_ROOT / ".env")
    if os.getenv("TTS_ENABLED", "false").strip().lower() not in ("true", "1", "yes"):
        return 0
    _ensure_pulse_server()
    try:
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        payload = json.loads(raw) if raw.strip() else {}
        text = (payload.get("text") or "").strip()
        event = payload.get("event", "")
        if not text:
            return 0
        text = language_normalizer.ensure_language(text)
        rate, pitch, voice = None, None, None
        agent_persona_id = persona_rewriter.detect_agent_persona(text)
        persona_id = agent_persona_id or os.getenv("TTS_PERSONA", "")
        if persona_id:
            result = persona_rewriter.rewrite(text, event, persona_id)
            text, rate, pitch, voice = (
                result.text,
                result.rate,
                result.pitch,
                result.voice,
            )
        audio_path = _synthesize(text, rate, pitch, voice)
        try:
            play_serialized(audio_path)
        finally:
            audio_path.unlink(missing_ok=True)
    except Exception:
        logging.exception("tts_speak_worker failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
