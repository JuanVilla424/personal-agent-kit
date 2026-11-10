#!/usr/bin/env python3
"""decision_integrations.py — the decision engine wired to the guard and to agent routing.

  guard_mutation()  → Noul("is it risky?") + Score("how risky?") → allow | challenge | block
  route_agent()     → Choice("which agent?") → delegate | escalate

Neither invents an answer. With the engine off or failing, guard_mutation() reports engine_ok
False and route_agent() escalates to the human.
"""

import json
import sys
from pathlib import Path
from typing import Any

THIS = Path(__file__).resolve()
REPO_ROOT = THIS.parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

from decision import (  # noqa: E402
    Choice,
    ChoiceAnswer,
    DecisionResult,
    Noul,
    NoulAnswer,
    Score,
    ScoreAnswer,
    composite_score,
    decide,
)

AGENT_CARDS = REPO_ROOT / "configs" / "agent-cards.json"
MIN_ROUTE_CONFIDENCE = 0.6  # below this, a person picks the agent
RISK_NAMES = ["read_only", "low", "medium", "high", "critical"]


def _agent_options() -> dict[str, str]:
    """The roster for a Choice: {agent id: label and intents}, {} when the cards cannot be read."""
    try:
        cards = json.loads(AGENT_CARDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    options = {}
    for agent_id, cfg in (cards.get("agents") or {}).items():
        intents = ", ".join(cfg.get("intents", []))
        label = cfg.get("label", agent_id)
        options[agent_id] = f"{label} ({intents})" if intents else label
    return options


def _engine_info(result: DecisionResult) -> dict[str, str]:
    """Which engine decided and, when it could not, why: a default is never silent."""
    info = {"engine": result.model}
    if result.degraded:
        info["engine_error"] = result.degraded
    return info


def route_agent(state: Any, _ask=None) -> dict[str, Any]:
    """Which persona handles this task: {agent, confidence, action}, delegate or escalate."""
    options = _agent_options()
    if not options:
        return {
            "agent": "",
            "confidence": 0.0,
            "action": "escalate",
            "engine_error": f"no roster in {AGENT_CARDS.name}",
        }
    result = decide(
        state, {"agent": Choice("Which agent should handle this task?", options)}, _ask=_ask
    )
    answer = result.answers.get("agent")
    if not isinstance(answer, ChoiceAnswer):
        return {"agent": "", "confidence": 0.0, "action": "escalate", **_engine_info(result)}
    return {
        "agent": answer.choice,
        "confidence": answer.confidence,
        "action": "delegate" if answer.confidence >= MIN_ROUTE_CONFIDENCE else "escalate",
        "probabilities": answer.probabilities,
        **_engine_info(result),
    }


GUARD_QUESTIONS = {
    "is_risky": Noul(
        "This action could cause damage, data loss, or a security risk if executed incorrectly",
    ),
    "risk_level": Score(
        "What is the risk level of this action?",
        levels=[
            "read_only: viewing data, no side effects",
            "low: config change, easily revertible",
            "medium: service restart, non-destructive mutation",
            "high: data mutation, permission change, credential rotation",
            "critical: deletion, database drop, irreversible action",
        ],
    ),
    "needs_challenge": Noul("A careful person would want the human's approval before this runs"),
    "is_prod": Noul("This action affects a production environment"),
    "cost_impact": Noul("This action could increase monthly costs by more than $500"),
}


def guard_mutation(state: Any, _ask=None) -> dict[str, Any]:
    """Judge a mutation BEFORE it runs: {action, risk_level, risk_score, confidence, reasons}."""
    result = decide(state, GUARD_QUESTIONS, _ask=_ask)

    # A default here would look like a real verdict. engine_ok=False tells the guard it is an
    # engine failure, which neither counts toward the halt nor passes as an answer.
    if result.degraded or not any(q in result.answers for q in GUARD_QUESTIONS):
        return {
            "action": "challenge",
            "risk_level": "unknown",
            "risk_score": 1.0,
            "confidence": 0.0,
            "reasons": [result.degraded or "the engine returned no usable answer"],
            "engine_ok": False,
        }

    is_risky = result.answers.get("is_risky")
    risk_level = result.answers.get("risk_level")
    needs_challenge = result.answers.get("needs_challenge")
    is_prod = result.answers.get("is_prod")
    cost_impact = result.answers.get("cost_impact")

    # a partial answer leans toward asking: in doubt, challenge
    risky_prob = is_risky.noul if isinstance(is_risky, NoulAnswer) else 0.5
    risk_val = risk_level.score if isinstance(risk_level, ScoreAnswer) else 2.0
    challenge_prob = needs_challenge.noul if isinstance(needs_challenge, NoulAnswer) else 0.5
    prod_prob = is_prod.noul if isinstance(is_prod, NoulAnswer) else 0.5
    cost_prob = cost_impact.noul if isinstance(cost_impact, NoulAnswer) else 0.0

    risk_score = composite_score(
        result,
        {
            "is_risky": 0.3,
            "risk_level": 0.3,
            "needs_challenge": 0.2,
            "is_prod": 0.1,
            "cost_impact": 0.1,
        },
    )

    reasons = []
    if risky_prob > 0.7:
        reasons.append(f"risky={risky_prob:.2f}")
    if challenge_prob > 0.7:
        reasons.append(f"needs_challenge={challenge_prob:.2f}")
    if prod_prob > 0.7:
        reasons.append(f"prod={prod_prob:.2f}")
    if cost_prob > 0.7:
        reasons.append(f"cost>500={cost_prob:.2f}")

    if risk_val >= 4 or risky_prob > 0.9:
        action = "block"
    elif risk_val <= 1 and risky_prob < 0.3 and risk_score < 0.3 and challenge_prob <= 0.6:
        action = "allow"
    else:
        action = "challenge"

    return {
        "action": action,
        "risk_level": RISK_NAMES[max(0, min(round(risk_val), len(RISK_NAMES) - 1))],
        "risk_score": round(risk_score, 3),
        "confidence": getattr(risk_level, "confidence", 0.0),
        "reasons": reasons,
    }
