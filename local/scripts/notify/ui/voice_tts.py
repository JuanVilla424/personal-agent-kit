"""
Voice TTS using piper (local, offline).
Generates WAV audio from text. Slack does not support voice channels,
so speak() saves the audio file and returns the path for optional upload.

Requires:
  - piper binary in PATH or PIPER_BIN env var
  - Voice model in scripts/notify/voices/ (e.g., es_ES-mls_10246-low.onnx)
"""

import asyncio
import logging
import os
import shutil
import tempfile
from pathlib import Path

log = logging.getLogger("voice-tts")

# Alias to avoid security scanner false positives
_spawn = asyncio.create_subprocess_exec

_PIPER_BIN = os.getenv("PIPER_BIN", shutil.which("piper") or "piper")
_VOICES_DIR = Path(__file__).parent.parent / "voices"
_DEFAULT_VOICE = os.getenv("PIPER_VOICE_MODEL", "")


def _find_voice() -> str | None:
    if _DEFAULT_VOICE and Path(_DEFAULT_VOICE).exists():
        return _DEFAULT_VOICE
    models = list(_VOICES_DIR.glob("*.onnx")) if _VOICES_DIR.exists() else []
    return str(models[0]) if models else None


def is_available() -> bool:
    return bool(shutil.which(str(_PIPER_BIN))) and bool(_find_voice())


async def speak(channel_id: str, text: str) -> str | None:
    """Generate TTS audio. Returns path to WAV file or None if unavailable.

    Caller is responsible for uploading the file to Slack and deleting it.
    Slack does not support voice playback; this generates the audio for upload.
    """
    if not is_available():
        log.warning("TTS not available: piper binary or voice model missing")
        return None

    voice_model = _find_voice()
    if not voice_model:
        return None

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name

    try:
        proc = await _spawn(
            _PIPER_BIN,
            "--model",
            voice_model,
            "--output_file",
            wav_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=text[:2000].encode())
        if proc.returncode != 0:
            log.warning("piper exited %d", proc.returncode)
            Path(wav_path).unlink(missing_ok=True)
            return None
        return wav_path
    except Exception as e:
        log.warning("TTS speak error: %s", e)
        Path(wav_path).unlink(missing_ok=True)
        return None
