"""Cross-process playback serialization for the Claude Code TTS hook.

Each hook event runs in its own short-lived, detached worker process (see
``tts_speak_worker.py``) — an in-memory queue would not survive between them.
Synthesis can happen concurrently across those processes; only actual audio
*playback* is serialized here, via an ``flock`` on a shared lock file, so two
spoken messages never overlap on the speakers.
"""

import fcntl
import logging
import math
import subprocess
import tempfile
import wave
from pathlib import Path
from shutil import which
from typing import Optional

logger = logging.getLogger(__name__)

LOCK_FILE = Path(tempfile.gettempdir()) / "claude-tts-playback.lock"

# A fixed timeout cut long responses off mid-sentence in practice: a 2310-character
# response, even at edge-tts's fastest auto-rate (+40%), genuinely takes over 100s to
# play — well past a flat 60s. MIN_TIMEOUT_SECONDS is the floor (short clips, or when
# duration can't be read); real playback gets duration * MARGIN_RATIO + MARGIN_SECONDS.
MIN_TIMEOUT_SECONDS = 60
TIMEOUT_MARGIN_RATIO = 1.1
TIMEOUT_MARGIN_SECONDS = 10


def find_player(audio_path: Path) -> list[str] | None:
    """Pick the first available audio player and build its command line.

    ``paplay`` is preferred over ``ffplay``: verified on this WSLg setup that
    ``ffplay`` (SDL2 audio backend) hangs indefinitely instead of honoring
    ``-autoexit`` against the WSLg PulseAudio RDP sink, while ``paplay`` (talks to
    PulseAudio directly, decodes mp3 via libsndfile) plays the full file and exits
    in real time — confirmed against ``ffprobe``'s reported duration. ``ffplay``
    stays as a fallback for setups where it behaves correctly; the ``timeout=`` in
    ``play_serialized`` is the safety net either way.

    Args:
        audio_path: Path to the audio file to play.

    Returns:
        The player command as a list of arguments, or ``None`` if neither
        ``paplay`` nor ``ffplay`` is installed.
    """
    if which("paplay"):
        return ["paplay", str(audio_path)]
    if which("ffplay"):
        return ["ffplay", "-nodisp", "-autoexit", "-loglevel", "error", str(audio_path)]
    return None


def _audio_duration_seconds(audio_path: Path) -> Optional[float]:
    """Read a WAV file's duration using the standard library only.

    Args:
        audio_path: Path to a WAV file.

    Returns:
        The duration in seconds, or None if the file can't be read as WAV (e.g. a
        non-WAV format slipped through, or a corrupt file) — the caller falls back
        to a fixed timeout in that case.
    """
    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            rate = wav_file.getframerate()
            return wav_file.getnframes() / float(rate) if rate else None
    except (wave.Error, EOFError, OSError):
        return None


def _timeout_for(audio_path: Path) -> int:
    """Pick a playback timeout long enough to cover the file's real duration.

    Args:
        audio_path: Path to the audio file to play.

    Returns:
        Never less than MIN_TIMEOUT_SECONDS; otherwise the real duration scaled by
        TIMEOUT_MARGIN_RATIO plus TIMEOUT_MARGIN_SECONDS of startup slack.
    """
    duration = _audio_duration_seconds(audio_path)
    if duration is None:
        return MIN_TIMEOUT_SECONDS
    return max(
        MIN_TIMEOUT_SECONDS,
        math.ceil(duration * TIMEOUT_MARGIN_RATIO) + TIMEOUT_MARGIN_SECONDS,
    )


def play_serialized(audio_path: Path, timeout: Optional[int] = None) -> None:
    """Play an audio file, holding an exclusive lock so playback never overlaps.

    Blocks the calling process (the detached worker, never the Claude Code hook
    itself) until any in-progress playback from another invocation finishes, then
    plays this file. Never raises — a missing player or a playback failure is
    logged and swallowed so a broken audio pipeline can never affect the session.

    Args:
        audio_path: Path to the audio file to play.
        timeout: Maximum seconds to allow the player to run before giving up. None
            (the default) computes it from the file's own duration (see
            `_timeout_for`) — a flat timeout was cutting long responses off
            mid-sentence in practice. Pass an explicit value only to override that.
    """
    cmd = find_player(audio_path)
    if cmd is None:
        logger.warning("no audio player found (ffplay/paplay) — skipping playback")
        return
    if timeout is None:
        timeout = _timeout_for(audio_path)
    try:
        LOCK_FILE.touch(exist_ok=True)
        with open(LOCK_FILE, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                result = subprocess.run(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=timeout,
                    check=False,
                )
                logger.info(
                    "playback finished (%s, exit=%d)", cmd[0], result.returncode
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "playback timed out after %ds (%s) — killed", timeout, cmd[0]
                )
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except Exception:
        logger.exception("playback failed for %s", audio_path)
