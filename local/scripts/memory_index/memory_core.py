#!/usr/bin/env python3
"""memory_core.py — how the memory ranks, replaces and summarizes, with no service around it.

memory_service.py and the benchmark (evals/memory_benchmark.py) share this module, so what is
measured is what runs.

  - Hybrid search: dense similarity finds a paraphrase, lexical BM25 finds an exact name, number or
    identifier that an embedding blurs. Reciprocal rank fusion merges the two rankings.
  - Replacement: a memory written with a `state_key` replaces the live one with the same key. The
    old one is kept with `superseded_by`, so nothing is deleted and the history stays readable.
  - Brief: the memories a session starts with, inside a character budget, the most important
    categories first and the newest first within each.

Stdlib only.
"""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

# BM25 parameters: the usual defaults for short documents.
BM25_K1 = 1.5
BM25_B = 0.75
# Reciprocal rank fusion constant: 60 is the value of the original paper, robust across corpora.
RRF_K = 60
# The categories, most important first: the brief fills its budget in this order.
CATEGORIES = ("security", "style", "systems", "business", "other")
# The Spanish names the first version stored; they are read as their English category.
CATEGORY_ALIASES = {
    "seguridad": "security",
    "estilo": "style",
    "sistemas": "systems",
    "negocio": "business",
    "otro": "other",
}
DEFAULT_CATEGORY = "other"
# Words too common to tell two memories apart, in the two languages the owner writes.
STOPWORDS = frozenset(
    "a an and are as at be by do does for from has have how i in is it its me my of on or our "
    "that the their them they this to was we what when where which who why will with you your "
    "el la los las un una unos unas y o de del al en por para con sin que qué es son está mi mis "
    "tu tus su sus se lo le les como cómo cuál cual cuándo dónde".split()
)
_WORD = re.compile(r"\w+", re.UNICODE)


def category_of(value: str) -> str:
    """The English category of a stored or requested value; unknown values are `other`."""
    value = (value or "").strip().lower()
    value = CATEGORY_ALIASES.get(value, value)
    return value if value in CATEGORIES else DEFAULT_CATEGORY


def _stem(word: str) -> str:
    """A light stem: a trailing plural or third-person `s` goes, so `drives` meets `drive`."""
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text: str) -> list[str]:
    """Lowercase words without accents and without stopwords."""
    folded = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return [word for word in _WORD.findall(plain) if word not in STOPWORDS]


def tokenize(text: str) -> list[str]:
    """The words, stemmed: `Puerto` and `puertos` match."""
    return [_stem(word) for word in words(text)]


class BM25Index:
    """Okapi BM25 over a small set of documents, rebuilt when the set changes."""

    def __init__(self, docs: Iterable[tuple[str, str]]):
        self.doc_terms: dict[str, Counter] = {}
        self.doc_len: dict[str, int] = {}
        for doc_id, text in docs:
            terms = tokenize(text)
            self.doc_terms[doc_id] = Counter(terms)
            self.doc_len[doc_id] = len(terms)
        total = len(self.doc_terms)
        self.avg_len = (sum(self.doc_len.values()) / total) if total else 0.0
        df: Counter = Counter()
        for terms in self.doc_terms.values():
            df.update(terms.keys())
        # BM25+ style idf: always positive, so a term in most documents still counts a little
        self.df = df
        self.idf = {term: math.log(1 + (total - n + 0.5) / (n + 0.5)) for term, n in df.items()}

    def scores(self, query: str) -> dict[str, float]:
        """Every document with at least one query term, and its score."""
        out: dict[str, float] = {}
        for term in set(tokenize(query)):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for doc_id, terms in self.doc_terms.items():
                tf = terms.get(term, 0)
                if not tf:
                    continue
                norm = 1 - BM25_B + BM25_B * (self.doc_len[doc_id] / (self.avg_len or 1))
                out[doc_id] = out.get(doc_id, 0.0) + idf * tf * (BM25_K1 + 1) / (
                    tf + BM25_K1 * norm
                )
        return out

    def has_rare_term(self, query: str, max_docs: int) -> bool:
        """Whether the query names something only a few memories hold: a hostname, a number,
        a codename. Such a lookup is lexical; an embedding blurs it."""
        return any(0 < self.df.get(term, 0) <= max_docs for term in set(tokenize(query)))

    def ranked(self, query: str, limit: int) -> list[str]:
        scores = self.scores(query)
        return sorted(scores, key=lambda doc_id: (-scores[doc_id], doc_id))[:limit]


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: each ranking adds 1 / (k + rank) to the ids it holds."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            fused[doc_id] = fused.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(fused.items(), key=lambda item: (-item[1], item[0]))


def _min_max(scores: dict[str, float], when_equal: float) -> dict[str, float]:
    """Scores scaled to 0..1; `when_equal` is what every document gets when all scores tie."""
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high == low:
        return {doc_id: when_equal for doc_id in scores}
    return {doc_id: (s - low) / (high - low) for doc_id, s in scores.items()}


def convex(
    dense: dict[str, float], lexical: dict[str, float], alpha: float
) -> list[tuple[str, float]]:
    """Convex combination of the two normalized scores: alpha × dense + (1 - alpha) × lexical.

    Unlike rank fusion it keeps how far apart the scores are: an exact identifier that only BM25
    sees is not tied with whatever the dense side happened to rank first.
    """
    # A tie means opposite things on each side. Equal dense similarities carry no order: no
    # credit. Equal BM25 scores mean equal evidence, such as the only document that holds a rare
    # identifier: full credit.
    dense_n, lexical_n = _min_max(dense, when_equal=0.0), _min_max(lexical, when_equal=1.0)
    fused = {
        doc_id: alpha * dense_n.get(doc_id, 0.0) + (1 - alpha) * lexical_n.get(doc_id, 0.0)
        for doc_id in set(dense_n) | set(lexical_n)
    }
    # on a tie, the memory that shares words with the question goes first
    return sorted(fused.items(), key=lambda item: (-item[1], -lexical_n.get(item[0], 0.0), item[0]))


def is_live(payload: dict) -> bool:
    """Whether a memory still holds: one replaced by a newer one is history, not an answer."""
    return not payload.get("superseded_by")


def brief(memories: list[dict], max_chars: int) -> list[dict]:
    """The memories a session starts with: most important category first, newest first within a
    category, and only whole memories that fit the character budget."""
    live = [m for m in memories if is_live(m)]
    order = {name: i for i, name in enumerate(CATEGORIES)}
    live.sort(key=lambda m: (order[category_of(m.get("category", ""))], -m.get("created_at", 0)))
    chosen, used = [], 0
    for memory in live:
        size = len(memory.get("text", "")) + 3  # the "- " bullet and the newline
        if used + size > max_chars:
            continue
        chosen.append(memory)
        used += size
    return chosen
