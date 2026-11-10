"""Coverage for core/chunker.py — paragraph and line splitting with code fences."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core import chunker as ch  # noqa: E402


def test_short_text_single_chunk():
    assert ch.chunk("hi", max_chars=100) == ["hi"]


def test_paragraph_split_is_labeled():
    text = "\n\n".join("para%d %s" % (i, "x" * 40) for i in range(8))
    chunks = ch.chunk(text, max_chars=100)
    assert len(chunks) > 1
    assert chunks[0].startswith("(Part 1/")


def test_oversized_paragraph_with_fence_splits_by_line():
    code = "\n".join("v%d = %d" % (i, i) for i in range(60))
    text = "```python\n" + code + "\n```"
    chunks = ch.chunk(text, max_chars=80)
    assert len(chunks) > 1


def test_single_huge_line_hard_split():
    chunks = ch.chunk("Z" * 400, max_chars=100)
    assert len(chunks) > 1
    assert all(len(c) <= 120 for c in chunks)
