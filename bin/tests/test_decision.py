"""The optional decision engine (bin/decision.py), its integrations and its MCP server.

No test reaches the network: the engine is replaced through `_ask`, or urlopen is faked.
"""

import io
import json
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "bin"))

import decision  # noqa: E402
import decision_integrations as di  # noqa: E402
import decision_mcp as dm  # noqa: E402
from decision import (  # noqa: E402
    Choice,
    ChoiceAnswer,
    DecisionResult,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
)


@pytest.fixture(autouse=True)
def no_key(monkeypatch, tmp_path):
    """No key unless a test sets one, and a .env of the test's own."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("PAK_DECISION_MODEL", raising=False)
    monkeypatch.setattr(decision, "ENV_FILE", tmp_path / ".env")


# ── Keys and model ───────────────────────────────────────────────────────────────────────────────


def test_the_key_comes_from_the_environment_or_the_env_file(monkeypatch, tmp_path):
    assert decision.engine_key() == ""
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=<openrouter-api-key>\n", encoding="utf-8")
    assert decision.engine_key() == ""  # a placeholder is not a key
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-or-file\n", encoding="utf-8")
    assert decision.engine_key() == "sk-or-file"
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    assert decision.engine_key() == "sk-or-env"
    monkeypatch.setenv("OPENROUTER_API_KEY", "CHANGEME")
    assert decision.engine_key() == "sk-or-file"


def test_without_python_dotenv_only_the_environment_counts(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=sk-or-file\n", encoding="utf-8")
    monkeypatch.setitem(sys.modules, "dotenv", None)
    assert decision.engine_key() == ""


def test_the_model_can_be_chosen(monkeypatch):
    assert decision.decision_model() == decision.DEFAULT_MODEL
    monkeypatch.setenv("PAK_DECISION_MODEL", "openrouter/other")
    assert decision.decision_model() == "openrouter/other"


def test_confidence_measures_how_peaked_a_distribution_is():
    assert decision.compute_confidence({"a": 1.0}) == 1.0
    assert decision.compute_confidence({"a": 0.5, "b": 0.5}) == 0.0
    assert decision.compute_confidence({"a": 0.9, "b": 0.1}) == pytest.approx(0.8)


# ── decide() ─────────────────────────────────────────────────────────────────────────────────────


QUESTIONS = {
    "pick": Choice("Which?", {"a": "first", "b": "second"}),
    "level": Score("How much?", ["low", "mid", "high"]),
    "yes": Noul("Is it?", criteria="it is"),
}


def test_without_a_key_the_engine_is_off_and_says_so():
    result = decision.decide({}, QUESTIONS)
    assert result.answers == {}
    assert result.degraded.startswith(decision.ENGINE_OFF)


def test_an_injected_engine_answers_or_fails_visibly():
    def ok(_state, _questions, model, timeout):
        assert (model, timeout) == (decision.DEFAULT_MODEL, decision.DEFAULT_TIMEOUT)
        return {"yes": NoulAnswer(0.9)}, ""

    result = decision.decide({}, {"yes": Noul("x")}, _ask=ok)
    assert result.answers["yes"].noul == 0.9 and result.degraded == ""

    result = decision.decide({}, {"yes": Noul("x")}, _ask=lambda *_a: ({}, "boom"))
    assert result.degraded == f"{decision.ENGINE_UNAVAILABLE}: boom"


def test_the_questions_go_out_in_the_api_schema():
    schema = decision._engine_questions(QUESTIONS)
    assert schema["pick"] == {
        "type": "choice",
        "instructions": "Which?",
        "criteria": QUESTIONS["pick"].options,
    }
    assert schema["level"]["criteria"] == ["low", "mid", "high"]
    assert schema["yes"]["criteria"] == {"true": "it is", "false": "no"}


def test_answers_are_parsed_and_malformed_ones_left_out():
    data = {
        "answers": {
            "pick": {"choice": "b", "probabilities": {"a": 0.2, "b": 0.8}},
            "level": {"score": 1.4, "probabilities": {"0": 0.1, "1": 0.5, "2": 0.4, "x": 0.0}},
            "yes": {"noul": 1.7},
        }
    }
    answers = decision._parse_answers(data, QUESTIONS)
    assert answers["pick"].choice == "b" and answers["pick"].confidence == pytest.approx(0.6)
    assert answers["level"].probabilities == {"low": 0.1, "mid": 0.5, "high": 0.4, "x": 0.0}
    assert answers["yes"].noul == 1.0  # clamped
    assert decision._parse_answers({"answers": {"pick": {"choice": "zzz"}}}, QUESTIONS) == {}


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_the_engine_call_sends_the_key_and_reads_every_answer(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    seen = {}

    def fake_urlopen(req, timeout):
        seen.update(
            auth=req.get_header("Authorization"), body=json.loads(req.data), timeout=timeout
        )
        answers = {"answers": {"yes": {"noul": 0.3}}}
        return _Response(json.dumps(answers).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    result = decision.decide({"k": "v"}, {"yes": Noul("x")})
    assert result.answers["yes"].noul == 0.3
    assert seen["auth"] == "Bearer sk-or-test"
    assert seen["body"]["model"] == "~typesafe/jev-latest"

    result = decision.decide({}, QUESTIONS)  # one answer for three questions
    assert "answered 1 of 3" in result.degraded


def test_a_failed_request_is_reported_never_swallowed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")

    def refused(_req, timeout):
        raise OSError(f"connection refused after {timeout}s")

    monkeypatch.setattr(urllib.request, "urlopen", refused)
    result = decision.decide(object(), {"yes": Noul("x")})
    assert "request failed: OSError" in result.degraded


def test_composite_score_weights_each_dimension():
    result = DecisionResult(
        answers={
            "risky": NoulAnswer(0.5),
            "level": ScoreAnswer(2.0, {"a": 0.0, "b": 0.0, "c": 1.0}, 1.0),
            "other": ChoiceAnswer("a", {"a": 1.0}, 1.0),
        }
    )
    assert decision.composite_score(
        result, {"risky": 0.5, "level": 0.5, "other": 1.0, "x": 1.0}
    ) == pytest.approx(0.25 + 0.5 * 2 / 3)
    assert (
        decision.composite_score(DecisionResult(answers={"r": NoulAnswer(1.0)}), {"r": 3.0}) == 1.0
    )


# ── guard_mutation() and route_agent() ───────────────────────────────────────────────────────────


def _guard_engine(risky, level, challenge, prod=0.0, cost=0.0):
    def ask(_state, _questions, _model, _timeout):
        return {
            "is_risky": NoulAnswer(risky),
            "risk_level": ScoreAnswer(level, {str(i): 0.2 for i in range(5)}, 0.4),
            "needs_challenge": NoulAnswer(challenge),
            "is_prod": NoulAnswer(prod),
            "cost_impact": NoulAnswer(cost),
        }, ""

    return ask


def test_guard_mutation_allows_challenges_and_blocks():
    allow = di.guard_mutation({}, _ask=_guard_engine(0.1, 0.0, 0.1))
    assert (allow["action"], allow["risk_level"]) == ("allow", "read_only")
    challenge = di.guard_mutation({}, _ask=_guard_engine(0.8, 2.0, 0.8, 0.8, 0.8))
    assert challenge["action"] == "challenge"
    assert challenge["reasons"] == [
        "risky=0.80",
        "needs_challenge=0.80",
        "prod=0.80",
        "cost>500=0.80",
    ]
    assert di.guard_mutation({}, _ask=_guard_engine(0.95, 1.0, 0.0))["action"] == "block"
    assert di.guard_mutation({}, _ask=_guard_engine(0.1, 4.0, 0.0))["action"] == "block"


def test_guard_mutation_never_invents_a_verdict():
    off = di.guard_mutation({})
    assert off["engine_ok"] is False and off["action"] == "challenge"
    assert off["reasons"][0].startswith(decision.ENGINE_OFF)
    empty = di.guard_mutation({}, _ask=lambda *_a: ({}, ""))
    assert empty["engine_ok"] is False


def test_a_partial_guard_answer_leans_toward_asking():
    def partial(_state, _questions, _model, _timeout):
        return {"is_risky": NoulAnswer(0.1)}, ""

    assert di.guard_mutation({}, _ask=partial)["action"] == "challenge"


def test_route_agent_reads_the_kit_roster():
    options = di._agent_options()
    assert set(options) == {"raven", "elena", "kai", "iris"}
    assert "security review" in options["raven"]


def test_route_agent_delegates_only_with_confidence(monkeypatch, tmp_path):
    def sure(_state, questions, _model, _timeout):
        assert set(questions["agent"].options) == {"raven", "elena", "kai", "iris"}
        return {"agent": ChoiceAnswer("raven", {"raven": 0.9, "kai": 0.1}, 0.8)}, ""

    assert di.route_agent({"task": "audit"}, _ask=sure)["action"] == "delegate"
    unsure = lambda *_a: ({"agent": ChoiceAnswer("kai", {"kai": 0.5}, 0.3)}, "")  # noqa: E731
    assert di.route_agent({}, _ask=unsure)["action"] == "escalate"
    off = di.route_agent({})
    assert (off["agent"], off["action"]) == ("", "escalate") and "engine_error" in off

    monkeypatch.setattr(di, "AGENT_CARDS", tmp_path / "missing.json")
    assert di.route_agent({})["engine_error"] == "no roster in missing.json"


def test_every_card_names_an_opencode_agent_the_kit_ships():
    cards = json.loads(di.AGENT_CARDS.read_text(encoding="utf-8"))["agents"]
    base = json.loads((REPO / "bin" / "opencode" / "opencode.base.json").read_text())
    assert {c["opencode_agent"] for c in cards.values()} <= set(base["agent"])


# ── MCP server ───────────────────────────────────────────────────────────────────────────────────


def test_the_server_tells_every_session_how_to_use_it():
    assert dm.mcp.instructions == dm.INSTRUCTIONS
    for tool in ("guard_mutation", "decide", "route_agent", "0.6"):
        assert tool in dm.INSTRUCTIONS


def test_mcp_decide_says_off_instead_of_inventing(monkeypatch):
    assert dm.decide("ctx", "q?")["engine"] == "off"
    failing = DecisionResult(answers={}, model="m", degraded="engine-unavailable: x")
    monkeypatch.setattr(decision, "decide", lambda *_a, **_k: failing)
    assert dm.decide("ctx", "q?") == {
        "error": "engine-unavailable: x",
        "engine": "m",
        "confidence": 0.0,
    }


@pytest.mark.parametrize(
    "kwargs, answer, expected",
    [
        ({}, NoulAnswer(0.25), {"type": "noul", "probability": 0.25}),
        (
            {"options": "a|b"},
            ChoiceAnswer("a", {"a": 0.7, "b": 0.3}, 0.4),
            {
                "type": "choice",
                "choice": "a",
                "confidence": 0.4,
                "probabilities": {"a": 0.7, "b": 0.3},
            },
        ),
        (
            {"levels": "low|high"},
            ScoreAnswer(0.5, {}, 0.2),
            {"type": "score", "score": 0.5, "confidence": 0.2},
        ),
    ],
)
def test_mcp_decide_shapes_each_kind_of_answer(monkeypatch, kwargs, answer, expected):
    def fake(_state, questions):
        kind = type(questions["q"])
        assert kind is {"options": Choice, "levels": Score}.get(next(iter(kwargs), ""), Noul)
        return DecisionResult(answers={"q": answer}, model="m", latency_ms=1.0)

    monkeypatch.setattr(decision, "decide", fake)
    out = dm.decide("ctx", "q?", **kwargs)
    assert out == {"engine": "m", "latency_ms": 1.0, **expected}


def test_mcp_guard_mutation_answers_from_the_rules(monkeypatch, tmp_path):
    import auto_guard

    monkeypatch.setattr(auto_guard, "GUARD_LOG", tmp_path / "guard.jsonl")
    monkeypatch.setattr(auto_guard, "APPROVALS_PATH", tmp_path / "approvals.json")
    auto_guard._reset_counters()
    blocked = dm.guard_mutation("git push --force origin main", "publish")
    assert (blocked["allowed"], blocked["rule"]) == (False, "force_push")
    assert dm.guard_mutation("ls -la") == {"allowed": True}
    challenged = dm.guard_mutation("git push origin main", "publish")
    assert challenged["approve"]["cmd"].startswith(auto_guard.APPROVE_CMD + " ")
    auto_guard._reset_counters()


def test_mcp_route_agent_escalates_without_the_engine():
    assert dm.route_agent("review this diff")["action"] == "escalate"
