"""edge-tts based implementation of TTSEngine.

Uses Microsoft Edge's neural voices via the unofficial ``edge-tts`` Python package —
no API key required, no local model to download. Network-dependent and backed by an
unofficial endpoint with no SLA; see docs/stories/tts-hook-persona.md for the
comparison against Piper (offline) and paid engines (ElevenLabs/OpenAI).
"""

import asyncio
import logging
import subprocess
import tempfile
import uuid
from pathlib import Path
from shutil import which
from typing import Optional

import edge_tts

from .base import TTSEngine

logger = logging.getLogger(__name__)

DEFAULT_VOICE = "en-US-GuyNeural"

# Text is never truncated (see tts_hook.py) — long responses are read faster instead
# of being cut off with a "continues" marker. Gentle ramp: +5% per 50 chars past
# LENGTH_THRESHOLD, capped at MAX_RATE_PERCENT so speech stays intelligible.
LENGTH_THRESHOLD = 300
RATE_STEP_PERCENT = 5
RATE_STEP_CHARS = 50
MAX_RATE_PERCENT = 40


def _length_ramp_percent(char_count: int) -> int:
    """How much the auto length-based speedup wants to add, before any persona.

    Args:
        char_count: Length of the text to be spoken.

    Returns:
        A percent (0 or positive) — 0 up to LENGTH_THRESHOLD, then +RATE_STEP_PERCENT
        per RATE_STEP_CHARS past it, capped at MAX_RATE_PERCENT.
    """
    if char_count <= LENGTH_THRESHOLD:
        return 0
    steps = (char_count - LENGTH_THRESHOLD) // RATE_STEP_CHARS
    return min(MAX_RATE_PERCENT, steps * RATE_STEP_PERCENT)


def _rate_percent(persona_rate: Optional[float], char_count: int) -> int:
    """Combine a persona's speed multiplier with the auto length-based speedup.

    A persona's rate is a baseline register (e.g. a calm 0.95, a brisk 1.08) — it
    used to fully replace the auto ramp for long text, which meant a very
    long response with a persona active never sped up past that fixed baseline. Now
    they add: a calm persona still picks up some pace for a very long response
    (rather than staying sluggish), and a brisk persona still respects the same
    intelligibility ceiling as everyone else at the extreme end.

    Args:
        persona_rate: The active persona's rate multiplier, or None (no persona —
            behaves exactly as before, pure length ramp).
        char_count: Length of the text to be spoken.

    Returns:
        A percent value, capped at MAX_RATE_PERCENT (not floored — a slow persona
        with short text can still legitimately be negative).
    """
    persona_percent = (
        round((persona_rate - 1.0) * 100) if persona_rate is not None else 0
    )
    return min(MAX_RATE_PERCENT, persona_percent + _length_ramp_percent(char_count))


def _percent_to_rate_string(percent: int) -> str:
    """Format a percent as edge-tts's signed rate string.

    Args:
        percent: A signed percent, e.g. 15 or -5.

    Returns:
        A rate string edge-tts accepts, e.g. ``"+15%"`` or ``"-5%"``.
    """
    return f"{'+' if percent >= 0 else ''}{percent}%"


def _pitch_to_hz_string(pitch: int) -> str:
    """Convert an abstract Hz shift (e.g. from a persona) to edge-tts's pitch format.

    Args:
        pitch: Pitch shift in Hz, 0 = normal.

    Returns:
        A signed Hz string edge-tts accepts, e.g. ``"+20Hz"`` or ``"-10Hz"``.
    """
    return f"{'+' if pitch >= 0 else ''}{pitch}Hz"


class EdgeTTSEngine(TTSEngine):
    """Synthesizes speech using edge-tts neural voices.

    Output is converted from edge-tts's native mp3 to WAV via ``ffmpeg`` before
    being handed back — verified on this box that ``paplay`` (the preferred
    player, see ``audio_queue.py``) can glitch/cut out decoding mp3 through
    libsndfile, while WAV plays back cleanly every time.
    """

    def __init__(self, voice: str = DEFAULT_VOICE) -> None:
        """Store the voice to use for synthesis.

        Args:
            voice: An edge-tts voice name (e.g. "en-US-GuyNeural").
        """
        self.voice = voice

    def synthesize(
        self,
        text: str,
        rate: Optional[float] = None,
        pitch: Optional[int] = None,
        voice: Optional[str] = None,
    ) -> Path:
        """Synthesize text with edge-tts and return the path to a playable WAV.

        Args:
            text: The text to synthesize.
            rate: Optional speed multiplier from an active persona (1.0 normal). Added
                to (not replaced by) the auto length-based speedup — see
                ``_rate_percent`` — so a persona's baseline pace and the need to keep
                very long responses from taking forever both apply together. None
                behaves exactly as if a neutral (1.0) persona were active.
            pitch: Optional pitch shift in Hz from an active persona. None keeps
                edge-tts's neutral pitch, exactly like before personas existed.
            voice: Optional edge-tts voice name from an active persona (e.g. a
                different BMAD agent's own voice in party-mode). None keeps this
                instance's own voice (``self.voice``, set at construction).

        Returns:
            Path to a temporary WAV file. The caller owns the file and must
            delete it once playback finishes.
        """
        rate_str = _percent_to_rate_string(_rate_percent(rate, len(text)))
        pitch_str = _pitch_to_hz_string(pitch) if pitch is not None else "+0Hz"
        voice_to_use = voice or self.voice
        mp3_path = Path(tempfile.gettempdir()) / f"claude-tts-{uuid.uuid4().hex}.mp3"
        communicate = edge_tts.Communicate(
            text, voice_to_use, rate=rate_str, pitch=pitch_str
        )
        asyncio.run(communicate.save(str(mp3_path)))
        wav_path = self._to_wav(mp3_path)
        logger.info(
            "edge-tts synthesized %d chars at rate %s, pitch %s, voice %s to %s",
            len(text),
            rate_str,
            pitch_str,
            voice_to_use,
            wav_path,
        )
        return wav_path

    def _to_wav(self, mp3_path: Path) -> Path:
        """Convert an mp3 file to WAV via ``ffmpeg``, deleting the mp3 afterwards.

        Falls back to returning the original mp3 path if ``ffmpeg`` is missing or
        the conversion fails — playback may glitch in that case, but the hook
        still has something to play rather than nothing.

        Args:
            mp3_path: Path to the source mp3 file.

        Returns:
            Path to the converted WAV file, or the original mp3 path on failure.
        """
        if not which("ffmpeg"):
            logger.warning("ffmpeg not found — playing mp3 directly, may glitch")
            return mp3_path
        wav_path = mp3_path.with_suffix(".wav")
        try:
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(mp3_path),
                    "-loglevel",
                    "error",
                    str(wav_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
                check=True,
            )
        except Exception:
            logger.exception("ffmpeg conversion to wav failed — playing mp3 directly")
            return mp3_path
        mp3_path.unlink(missing_ok=True)
        return wav_path
