"""Abstract base class for TTS engines used by the Claude Code TTS hook."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class TTSEngine(ABC):
    """Base interface every TTS engine must implement.

    Adding a new engine means creating a new module in this package with a class
    implementing this interface and registering it in ``tts_engines/__init__.py``'s
    ``ENGINES`` dict — never adding a conditional branch to the hook's own logic.
    """

    @abstractmethod
    def synthesize(
        self,
        text: str,
        rate: Optional[float] = None,
        pitch: Optional[int] = None,
        voice: Optional[str] = None,
    ) -> Path:
        """Synthesize text to speech and return the path to the resulting audio file.

        Args:
            text: The text to synthesize. Callers are responsible for any cleanup
                or truncation before calling this method.
            rate: Optional speed multiplier (1.0 normal, 1.05 = 5% faster), e.g. from
                an active TTS_PERSONA. None means the engine picks its own default
                (an engine may still auto-speed-up long text on its own in that case).
            pitch: Optional pitch shift in Hz (0 normal), e.g. from an active
                TTS_PERSONA. None means the engine's own neutral default.
            voice: Optional engine-specific voice identifier, e.g. from an active
                persona (different BMAD agents speak with different voices in
                party-mode). None means the engine's own default voice. An engine
                whose voice scheme doesn't map onto this identifier (e.g.
                Chatterbox's own voice files) may accept and ignore it — see that
                engine's own docstring, same as it already does for `pitch`.

        Returns:
            Path to a generated audio file (any format the configured player accepts).
            The caller owns the file and is responsible for deleting it.

        Raises:
            Exception: Any engine-specific failure. Callers must catch broadly and
                degrade gracefully — this hook must never fail the calling session.
        """
        raise NotImplementedError
