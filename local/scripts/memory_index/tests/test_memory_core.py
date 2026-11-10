"""memory_core.py: tokenizing, BM25, rank fusion, replacement and the brief."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory_core as core  # noqa: E402


def test_tokenize_folds_case_and_accents_and_drops_stopwords():
    assert core.tokenize("¿Cuál es el PUERTO de Grafana?") == ["puerto", "grafana"]
    assert core.tokenize("The port of the API") == ["port", "api"]


def test_bm25_prefers_the_rarer_term_and_ignores_unknown_ones():
    index = core.BM25Index(
        [
            ("a", "grafana listens on port 3007"),
            ("b", "grafana dashboards for the team"),
            ("c", "the team lunch is on friday"),
        ]
    )
    assert index.ranked("grafana 3007", 3)[0] == "a"
    assert index.scores("nothing matches here") == {}
    assert core.BM25Index([]).ranked("anything", 3) == []


def test_rrf_rewards_agreement_between_rankings():
    fused = core.rrf([["a", "b", "c"], ["b", "a"]])
    assert [doc for doc, _ in fused][:2] == ["a", "b"] or [doc for doc, _ in fused][:2] == [
        "b",
        "a",
    ]
    assert dict(fused)["c"] < dict(fused)["a"]
    assert core.rrf([]) == []


def test_category_of_reads_old_names_and_defaults_to_other():
    assert core.category_of("Seguridad") == "security"
    assert core.category_of("style") == "style"
    assert core.category_of("") == core.category_of(None) == "other"


def test_brief_orders_by_category_then_recency_and_skips_what_does_not_fit():
    memories = [
        {"text": "old style", "category": "style", "created_at": 1},
        {"text": "new style", "category": "style", "created_at": 2},
        {"text": "a security rule", "category": "security", "created_at": 0},
        {"text": "replaced", "category": "security", "created_at": 3, "superseded_by": "x"},
        {"text": "y" * 50, "category": "other", "created_at": 5},
        {"text": "short", "category": "other", "created_at": 4},
    ]
    texts = [m["text"] for m in core.brief(memories, max_chars=50)]
    assert texts == ["a security rule", "new style", "old style", "short"]
    assert core.brief([], max_chars=10) == []
