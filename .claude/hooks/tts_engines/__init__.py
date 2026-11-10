"""Registry mapping ``TTS_ENGINE`` values to their engine classes.

Adding a new engine: create a new module in this package with a class implementing
``TTSEngine`` (see ``base.py``), then add one line to ``ENGINES`` below. Never add a
conditional branch to the hook's own logic to select an engine.
"""

from .base import TTSEngine
from .chatterbox_engine import ChatterboxEngine
from .edge_tts_engine import EdgeTTSEngine

ENGINES: dict[str, type[TTSEngine]] = {
    "edge-tts": EdgeTTSEngine,
    "chatterbox": ChatterboxEngine,
}
