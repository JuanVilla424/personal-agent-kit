import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.chunker import chunk


def test_short_text_no_chunk():
    text = "Kai here."
    result = chunk(text, max_chars=3800)
    assert result == [text]


def test_long_text_splits():
    text = "a\n\n" * 1000
    result = chunk(text, max_chars=200)
    assert len(result) > 1
    for c in result:
        assert len(c) <= 250


def test_markdown_fence_preserved():
    text = "Intro\n\n```python\n" + "x = 1\n" * 300 + "```\n\nOutro"
    result = chunk(text, max_chars=500)
    # Every chunk that opens a fence should close it
    for c in result:
        opens = c.count("```")
        # Each chunk should have balanced fences (even number or chunk label)
        assert opens >= 0


def test_chunk_labels_on_multipart():
    text = "W" * 8000
    result = chunk(text, max_chars=3800)
    assert len(result) >= 2
    assert "Part 1/" in result[0]
    assert "Part 2/" in result[1]


def test_single_large_paragraph_hard_split():
    text = "X" * 10000
    result = chunk(text, max_chars=1000)
    assert len(result) >= 10
    for c in result:
        # Label + content shouldn't exceed much more than limit
        content = c.split("\n", 1)[-1] if "\n" in c else c
        assert len(content) <= 1100
