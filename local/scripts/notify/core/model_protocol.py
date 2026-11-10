"""Resolve which protocol variant (full/compact/ultra) a model should load.

Reads ``configs/model-protocol-map.yaml`` so the agent loads protocols that fit the model's context
window (compact for small windows). Keeps the protocol load within budget per model. See MODELS.md.
"""

from pathlib import Path

import yaml

_MAP_PATH = Path(__file__).resolve().parents[4] / "configs" / "model-protocol-map.yaml"
_VARIANT_DIR = {"full": "protocols", "compact": "protocols/compact", "ultra": "protocols/ultra"}


def _load() -> dict:
    try:
        return yaml.safe_load(_MAP_PATH.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def variant_for(model: str) -> str:
    """Protocol variant for a model: its mapped variant if listed, else the default."""
    cfg = _load()
    entry = (cfg.get("models") or {}).get(model) or {}
    return entry.get("variant") or cfg.get("default_variant", "full")


def directive_for(model: str) -> str:
    """One-line system-prompt directive telling the agent which protocol variant to read."""
    variant = variant_for(model)
    folder = _VARIANT_DIR.get(variant, "protocols")
    return (
        f"\n\n🧩 Protocol variant for your model ({model}): **{variant}** — when reading a "
        f"protocol, use it from `{folder}/` (sized to your context window; see MODELS.md)."
    )
