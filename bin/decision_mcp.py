#!/usr/bin/env python3
"""bin/decision_mcp.py — MCP server exposing the guard and the decision engine to every agent.

Tools:
  guard_mutation()  → can I run this? → allow, challenge or block. Always works.
  decide()          → weighs options with a distribution and a confidence. Needs the engine.
  route_agent()     → who should take this? → agent and confidence. Needs the engine.

Without OPENROUTER_API_KEY the engine is off: guard_mutation() answers from the rules, and the
other two say so instead of inventing an answer.

Run (stdio): .venv/bin/python3 <this file>
Wiring: .mcp.json (Claude Code) and bin/opencode/build-config.sh (OpenCode)
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "bin"))

from mcp.server import MCPServer  # noqa: E402

# Claude Code injects these into the system prompt of every session.
INSTRUCTIONS = """\
Guard and decision layer of the repo (protocols/decision-protocol.md).
- About to mutate something that is not a plain shell command → guard_mutation(action, intent)
  BEFORE running it. allow = go on. challenge = ask the human, and never rephrase the action to get
  past it. block = do not run it, find a safer path. engine_unavailable = the guard could not
  evaluate, which is not a verdict: retry or ask the human.
- Shell commands already go through the same rules on their own (hook or plugin).
- Weighing options → decide(context, question, options). About to delegate → route_agent(task).
  Both need OPENROUTER_API_KEY; with engine "off", decide yourself or ask the human.
- Confidence below 0.6 → do not act alone: ask the human."""

mcp = MCPServer("agent-decision", instructions=INSTRUCTIONS)


def _off(detail: str) -> dict:
    return {"engine": "off", "confidence": 0.0, "detail": detail}


@mcp.tool()
def decide(context: str, question: str, options: str = "", levels: str = "") -> dict:
    """Weighs a question with a calibrated confidence: the distribution, not only the winner.

    Args:
        context: The situation you are evaluating
        question: The specific question (e.g. "Which approach is safer?")
        options: Options separated by | (e.g. "rollback|patch|ignore"). Empty = yes/no.
        levels: Ordered levels for a score (e.g. "low|medium|high|critical"), used instead of
                discrete options.
    """
    from decision import ENGINE_OFF, Choice, Noul, Score
    from decision import decide as _decide

    if options:
        opts = {o.strip(): o.strip() for o in options.split("|")}
        questions = {"q": Choice(instructions=question, options=opts)}
    elif levels:
        lvls = [level.strip() for level in levels.split("|")]
        questions = {"q": Score(instructions=question, levels=lvls)}
    else:
        questions = {"q": Noul(instructions=question)}

    result = _decide({"context": context}, questions)
    answer = result.answers.get("q")
    if answer is None:
        if result.degraded.startswith(ENGINE_OFF):
            return _off("OPENROUTER_API_KEY is not set: decide yourself or ask the human")
        return {"error": result.degraded, "engine": result.model, "confidence": 0.0}

    out = {"engine": result.model, "latency_ms": result.latency_ms}
    if hasattr(answer, "noul"):
        out.update({"type": "noul", "probability": round(answer.noul, 3)})
    elif hasattr(answer, "choice"):
        out.update(
            {
                "type": "choice",
                "choice": answer.choice,
                "confidence": round(answer.confidence, 3),
                "probabilities": {k: round(v, 3) for k, v in answer.probabilities.items()},
            }
        )
    else:
        out.update(
            {
                "type": "score",
                "score": round(answer.score, 2),
                "confidence": round(answer.confidence, 3),
            }
        )
    return out


@mcp.tool()
def guard_mutation(action: str, intent: str = "") -> dict:
    """Judges whether a mutation is safe BEFORE running it.

    The rules always run. The engine adds its judgment when it has a key. A challenge asks the
    human unless the human turned auto-approval on; a block is never approved.

    Args:
        action: The command or action about to be executed
        intent: What the human asked for
    """
    from auto_guard import guard, guard_response

    result = guard(user_intent=intent, action_text=action, log_engine="mcp")
    return guard_response(result, intent, action)


@mcp.tool()
def route_agent(task: str, context: str = "") -> dict:
    """Determines which persona should handle this task, with a confidence.

    Use it BEFORE delegating. With an action of "escalate", the human picks.

    Args:
        task: Description of the task to delegate
        context: Extra context
    """
    from decision_integrations import route_agent as _route

    return _route({"task": task, "context": context})


if __name__ == "__main__":
    mcp.run()
