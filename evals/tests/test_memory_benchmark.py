"""evals/memory_benchmark.py without the embedding model: the dataset, the scoring rules and the
Hermes-like baseline. The full run (it embeds every memory) is documented in
docs/memory-benchmark.md."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import memory_benchmark as mb  # noqa: E402


def test_the_dataset_is_consistent():
    memories, questions = mb.load_dataset()
    ids = {m["id"] for m in memories}
    assert len(ids) == len(memories)
    assert all(q["answer"] in ids for q in questions)
    assert {q["split"] for q in questions} == {"dev", "test"}
    assert {q["kind"] for q in questions} == {"exact", "paraphrase", "update", "crosslingual"}
    stale = mb.stale_versions(memories)
    # an update question asks for the newest version of its fact
    for q in questions:
        if q["kind"] == "update":
            key = next(m["state_key"] for m in memories if m["id"] == q["answer"])
            newest = [m["id"] for m in memories if m.get("state_key") == key][-1]
            assert q["answer"] == newest and stale[q["answer"]]


def test_the_stream_is_the_same_every_run():
    memories, _ = mb.load_dataset()
    first, second = mb.build_stream(memories), mb.build_stream(memories)
    assert first == second
    assert len(first) == len(memories) * (1 + mb.NOISE_PER_MEMORY)


def test_an_outdated_version_seen_first_is_a_miss():
    assert mb.rank_of(["a", "b"], "b", set()) == 2
    assert mb.rank_of(["old", "new"], "new", {"old"}) is None
    assert mb.rank_of(["new", "old"], "new", {"old"}) == 1
    assert mb.rank_of(["x"] * 10 + ["a"], "a", set()) is None
    assert mb.metrics([1, 2, None, None]) == {"hit@1": 0.25, "hit@5": 0.5, "mrr@5": 0.375}


def test_the_hermes_like_baseline_injects_newest_first_and_searches_the_rest():
    stream = [
        {"id": "a", "text": "The garage Pi is called bramble", "category": "systems"},
        {"id": "b1", "text": "Laptop is a ThinkPad", "category": "systems", "state_key": "laptop"},
        {
            "id": "b2",
            "text": "Laptop is now a Framework",
            "category": "systems",
            "state_key": "laptop",
        },
    ]
    hermes = mb.HermesLike(stream)
    assert hermes.injected == {"a", "b2"}  # the replaced version never reaches the files
    assert hermes.search("anything", "a") == ["a"]
    tight = mb.HermesLike(stream * 1)
    tight.injected = set()
    assert tight.search("What is bramble?", "a")[0] == "a"
    assert tight.search("???", "a") == []
