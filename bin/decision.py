#!/usr/bin/env python3
"""decision.py — the optional decision engine: calibrated answers instead of a guess.

Three primitives, each with a confidence computed from a forced distribution:

  Choice  → an option, its distribution and a confidence
  Score   → a value on a scale, its distribution and a confidence
  Noul    → a probability from 0 to 1 (yes or no)

The engine is one model behind OpenRouter's Decisions API, with no fallback to another model. It
needs OPENROUTER_API_KEY in the environment or in the repo's .env. Without the key the layer is
off, which is a normal state: decide() answers `engine-off`, and the callers fall back to the
deterministic rules or to the human. If the engine fails, decide() answers `engine-unavailable`
with the reason. Neither is ever passed off as a decision.

Importable:
    from decision import decide, Choice, Score, Noul, composite_score
"""

import json
import os
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

THIS = Path(__file__).resolve()
REPO_ROOT = THIS.parents[1]

DEFAULT_MODEL = "openrouter/~typesafe/jev-latest"
DEFAULT_TIMEOUT = 15
ENGINE_URL = "https://openrouter.ai/api/alpha/decisions"
ENGINE_KEY = "OPENROUTER_API_KEY"
ENGINE_OFF = "engine-off"
ENGINE_UNAVAILABLE = "engine-unavailable"
ENV_FILE = REPO_ROOT / ".env"


def _is_placeholder(value: str) -> bool:
    """A template value nobody filled in (`<openrouter-api-key>`, CHANGEME), not a key."""
    return (value.startswith("<") and value.endswith(">")) or value == "CHANGEME"


def _env_key(name: str) -> str:
    """`name` from the process environment, else from the repo's .env ('' if absent).

    A client started before the key was added spawns its hooks and MCP servers without it.
    """
    value = os.environ.get(name, "")
    if value and not _is_placeholder(value):
        return value
    try:
        from dotenv import dotenv_values
    except ImportError:
        return ""  # a bare python3 outside the venv: the environment is all it has
    value = dotenv_values(ENV_FILE).get(name) or ""
    return "" if _is_placeholder(value) else value


def engine_key() -> str:
    """The decision engine's key, '' when the layer is off."""
    return _env_key(ENGINE_KEY)


def decision_model() -> str:
    """The engine's model: PAK_DECISION_MODEL when set, else the default."""
    return os.environ.get("PAK_DECISION_MODEL") or DEFAULT_MODEL


# ── Primitives ───────────────────────────────────────────────────────────────────────────────────


@dataclass
class Choice:
    """Which of these options?"""

    instructions: str
    options: dict[str, str]  # {option_name: description}


@dataclass
class Score:
    """Which level on this scale?"""

    instructions: str
    levels: list[str]  # ordered: ["low: ...", "medium: ...", "high: ..."]


@dataclass
class Noul:
    """Is this true?"""

    instructions: str
    criteria: str = ""  # optional clarification of what yes means


@dataclass
class ChoiceAnswer:
    choice: str
    probabilities: dict[str, float]
    confidence: float


@dataclass
class ScoreAnswer:
    score: float  # continuous position along the levels
    probabilities: dict[str, float]
    confidence: float


@dataclass
class NoulAnswer:
    noul: float  # 0.0 = definitively no, 1.0 = definitively yes


@dataclass
class DecisionResult:
    answers: dict[str, Any]
    latency_ms: float = 0.0
    model: str = ""
    degraded: str = ""  # "" = a real answer; otherwise why there is none


def compute_confidence(probabilities: dict[str, float]) -> float:
    """(N × max_prob - 1) / (N - 1): how peaked the distribution is."""
    values = list(probabilities.values())
    n = len(values)
    if n <= 1:
        return 1.0
    peak = max(values)
    return max(0.0, min(1.0, (n * peak - 1) / (n - 1)))


# ── The engine ───────────────────────────────────────────────────────────────────────────────────


def _engine_questions(questions: dict) -> dict:
    """Our primitives → the API's schema (choice criteria is a record, score an array)."""
    out: dict[str, dict] = {}
    for qid, q in questions.items():
        if isinstance(q, Choice):
            out[qid] = {
                "type": "choice",
                "instructions": q.instructions,
                "criteria": dict(q.options),
            }
        elif isinstance(q, Score):
            out[qid] = {
                "type": "score",
                "instructions": q.instructions,
                "criteria": list(q.levels),
            }
        elif isinstance(q, Noul):
            out[qid] = {
                "type": "noul",
                "instructions": q.instructions,
                "criteria": {"true": q.criteria or "yes", "false": "no"},
            }
    return out


def _parse_answers(data: dict, questions: dict) -> dict[str, Any]:
    """The API's answers as our typed answers. A malformed one is left out."""
    answers: dict[str, Any] = {}
    for qid, q in questions.items():
        entry = (data.get("answers") or {}).get(qid) or {}
        probs = {
            str(k): float(v)
            for k, v in (entry.get("probabilities") or {}).items()
            if isinstance(v, (int, float))
        }
        confidence = float(entry.get("confidence", compute_confidence(probs) if probs else 0.0))
        if isinstance(q, Noul) and isinstance(entry.get("noul"), (int, float)):
            answers[qid] = NoulAnswer(noul=max(0.0, min(1.0, float(entry["noul"]))))
        elif isinstance(q, Choice) and entry.get("choice") in q.options:
            answers[qid] = ChoiceAnswer(
                choice=entry["choice"], probabilities=probs, confidence=confidence
            )
        elif isinstance(q, Score) and isinstance(entry.get("score"), (int, float)):
            # score probabilities come keyed by level index; the answers use the level text
            by_level = {
                (q.levels[int(k)] if k.isdigit() and int(k) < len(q.levels) else k): v
                for k, v in probs.items()
            }
            answers[qid] = ScoreAnswer(
                score=float(entry["score"]), probabilities=by_level, confidence=confidence
            )
    return answers


def _ask_engine(state: Any, questions: dict, model: str, timeout: int) -> tuple[dict, str]:
    """Ask the engine: (typed answers, "") or ({}, why it failed)."""
    payload = {
        "model": model.removeprefix("openrouter/"),
        "state": state if isinstance(state, (str, dict, list)) else str(state),
        "questions": _engine_questions(questions),
    }
    req = urllib.request.Request(
        ENGINE_URL,
        data=json.dumps(payload, default=str).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + engine_key(),
            "User-Agent": "personal-agent-kit/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:  # pylint: disable=broad-except
        return {}, f"request failed: {type(e).__name__}: {e}"[:300]
    answers = _parse_answers(data, questions)
    # All or nothing: a partial answer counts as unavailable.
    if len(answers) != len(questions):
        return {}, f"answered {len(answers)} of {len(questions)} questions"
    return answers, ""


def decide(
    state: Any,
    questions: dict[str, Any],
    timeout: int = DEFAULT_TIMEOUT,
    _ask: Callable[..., tuple[dict, str]] | None = None,
) -> DecisionResult:
    """One call, every question answered. `_ask` replaces the engine in tests."""
    start = time.time()
    model = decision_model()
    if _ask is None and not engine_key():
        return DecisionResult(
            answers={}, model=model, degraded=f"{ENGINE_OFF}: {ENGINE_KEY} is not set"
        )
    answers, error = (_ask or _ask_engine)(state, questions, model, timeout)
    return DecisionResult(
        answers=answers,
        latency_ms=round((time.time() - start) * 1000, 1),
        model=model,
        degraded=f"{ENGINE_UNAVAILABLE}: {error}" if error else "",
    )


def composite_score(result: DecisionResult, weights: dict[str, float]) -> float:
    """Combine several dimensions with weights kept in code, so a changed priority is a changed
    coefficient, not a changed prompt. Each key is a question id; a scale counts from 0 to 1."""
    total = 0.0
    for qid, weight in weights.items():
        answer = result.answers.get(qid)
        if isinstance(answer, NoulAnswer):
            total += weight * answer.noul
        elif isinstance(answer, ScoreAnswer):
            total += weight * (answer.score / _max_level(answer))
    return min(1.0, total)


def _max_level(answer: ScoreAnswer) -> float:
    """The top index of the answer's scale; a four-level scale when the answer names no levels."""
    return float(max(len(answer.probabilities) - 1, 3))
