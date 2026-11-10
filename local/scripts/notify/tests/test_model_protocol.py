"""Coverage for core/model_protocol.py — model → protocol-variant resolution."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import model_protocol as mp  # noqa: E402


def test_listed_model_uses_mapped_variant():
    assert mp.variant_for("claude-opus-5-5") == "full"
    assert mp.variant_for("claude-haiku-5-5") == "full"


def test_unlisted_model_falls_back_to_default():
    assert mp.variant_for("some-unknown-model") == "full"


def test_directive_mentions_variant_and_dir():
    d = mp.directive_for("claude-opus-5-5")
    assert "full" in d and "protocols/" in d and "claude-opus-5-5" in d


def test_compact_model_resolves_and_points_to_compact(monkeypatch, tmp_path):
    fake = tmp_path / "map.yaml"
    fake.write_text(
        "default_variant: full\nmodels:\n  tiny-model: {window: 40000, variant: compact}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mp, "_MAP_PATH", fake)
    assert mp.variant_for("tiny-model") == "compact"
    assert "protocols/compact/" in mp.directive_for("tiny-model")


def test_missing_map_falls_back_to_full(monkeypatch, tmp_path):
    monkeypatch.setattr(mp, "_MAP_PATH", tmp_path / "nope.yaml")
    assert mp.variant_for("anything") == "full"
