"""Chatterbox TTS engine — self-hosted (MIT), used as the offline fallback for edge-tts.

Talks to a local Chatterbox-TTS-Server instance (see
local/scripts/chatterbox-tts-server/, a git submodule of
https://github.com/devnen/Chatterbox-TTS-Server) over its native ``/tts`` endpoint.
Each engineer runs their own instance (docker compose, port 8004) — nothing is shared
or sent to a third party.

Not used as the primary engine: measured on this box at ~15x slower than real-time on
CPU (see docs/stories/tts-hook-persona.md, Historia C) — a full Claude response could
take tens of minutes. It exists as ``TTS_FALLBACK_ENGINE``, tried only when the primary
engine (edge-tts — network-dependent, unofficial endpoint, no SLA) fails outright. See
``tts_speak_worker.py``'s ``_synthesize()`` for the fallback logic. Slow-but-audible
beats silent in that one specific case; it is never the common path.

Chatterbox's API has no pitch control — the ``pitch`` parameter is accepted for
interface compatibility only and has no effect.
"""

import logging
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import requests

from .base import TTSEngine

logger = logging.getLogger(__name__)

DEFAULT_URL = "http://localhost:8004"
DEFAULT_VOICE = "Emily.wav"
DEFAULT_LANGUAGE = "en"
DEFAULT_EXAGGERATION = 1.3  # matches config.yaml's own generation_defaults
# CPU inference measured at ~15x slower than real-time (Historia C) — a long response
# can legitimately take minutes to synthesize. This is the fallback path, not the
# common case, so a generous ceiling is fine; it only ever blocks the detached worker.
REQUEST_TIMEOUT_SECONDS = 600


class ChatterboxEngine(TTSEngine):
    """Synthesizes speech via a local, self-hosted Chatterbox-TTS-Server instance."""

    def __init__(
        self,
        url: str = DEFAULT_URL,
        voice: str = DEFAULT_VOICE,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        """Store the server URL, voice, and language to request on every call.

        Args:
            url: Base URL of the local Chatterbox-TTS-Server instance.
            voice: Filename of a predefined voice bundled with the server.
            language: Language code passed to the server (e.g. "es").
        """
        self.url = url
        self.voice = voice
        self.language = language

    def synthesize(
        self,
        text: str,
        rate: Optional[float] = None,
        pitch: Optional[int] = None,
        voice: Optional[str] = None,
    ) -> Path:
        """Synthesize text via the local Chatterbox server and return a WAV path.

        Args:
            text: The text to synthesize.
            rate: Optional speed multiplier — maps directly to Chatterbox's own
                ``speed_factor``. None uses the server's own default (1.0).
            pitch: Accepted for interface parity only — Chatterbox's API has no
                pitch control, so this has no effect.
            voice: Accepted for interface parity only — a persona's `voice` is an
                edge-tts voice name (e.g. "es-CO-GonzaloNeural"), which doesn't map
                onto Chatterbox's own voice files (`predefined_voice_id`, set at
                construction), so this has no effect either.

        Returns:
            Path to a temporary WAV file. The caller owns the file and must
            delete it once playback finishes.

        Raises:
            requests.RequestException: If the local server is unreachable, not
                running, or returns an error.
        """
        del pitch, voice  # unsupported by this engine's API — kept for interface parity
        payload = {
            "text": text,
            "voice_mode": "predefined",
            "predefined_voice_id": self.voice,
            "language": self.language,
            "exaggeration": DEFAULT_EXAGGERATION,
            "output_format": "wav",
        }
        if rate is not None:
            payload["speed_factor"] = rate
        response = requests.post(
            f"{self.url}/tts", json=payload, timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        wav_path = Path(tempfile.gettempdir()) / f"claude-tts-{uuid.uuid4().hex}.wav"
        wav_path.write_bytes(response.content)
        logger.info(
            "chatterbox synthesized %d chars (voice=%s) to %s",
            len(text),
            self.voice,
            wav_path,
        )
        return wav_path
