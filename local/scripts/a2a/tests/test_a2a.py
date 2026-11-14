"""local/scripts/a2a/a2a.py — delegate, send, registry and verdict machinery, all hermetic."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "local" / "scripts" / "a2a"))
sys.path.insert(0, str(REPO / "bin"))

import a2a  # noqa: E402
from auto_guard import GuardResult  # noqa: E402

CARDS = {
    "agents": {
        "raven": {
            "opencode_agent": "security-agent",
            "label": "Raven, cybersecurity specialist",
            "intents": ["security review", "threat modeling"],
        },
        "iris": {
            "opencode_agent": "reports-agent",
            "label": "Iris, report generation specialist",
            "intents": ["Excel reports", "PDF reports"],
        },
        "elena": {
            "opencode_agent": "database",
            "label": "Elena, database architect",
            "intents": ["schema review"],
        },
        "kai": {
            "opencode_agent": "infra-agent",
            "label": "Kai, infrastructure engineer",
            "intents": ["automation"],
        },
    }
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    registry = tmp_path / "a2a.jsonl"
    monkeypatch.setattr(a2a, "REGISTRY", registry)
    monkeypatch.setattr(a2a, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(a2a, "BUS", tmp_path / "a2a_bus.jsonl")
    monkeypatch.setattr(a2a, "CURSORS_DIR", tmp_path)
    return registry


def allow(_user_intent, _action_text, **_kw):
    return GuardResult(action="allow")


def test_the_real_cards_load_and_route():
    cards = a2a.load_cards()
    assert cards["agents"]["raven"]["opencode_agent"] == "security-agent"


def test_validate_rejects_unknown_persona_intent_cid_and_hop(env):
    ok = a2a.validate("raven", "security review", "a2a-1234abcd", 1, CARDS)
    assert ok is None
    assert "unknown persona" in a2a.validate("nope", "security review", "a2a-1234abcd", 1, CARDS)
    assert "does not take intent" in a2a.validate(
        "raven", "cost validation", "a2a-1234abcd", 1, CARDS
    )
    assert "invalid correlation_id" in a2a.validate("raven", "security review", "bad!", 1, CARDS)
    assert a2a.validate("raven", "security review", "a2a-1234abcd", 3, CARDS) is None


def test_the_request_block_has_the_protocol_shape():
    block = a2a.build_request_block("Raven", "security review", "t", "c", "[INTERNAL]", "a2a-x1", 1)
    assert block.startswith("[A2A → Raven | hop:1/3]")
    assert "intent: security review" in block and "correlation_id: a2a-x1" in block


def test_extract_verdict_prefers_the_fenced_block_with_the_cid():
    cid = "a2a-abc12345"
    out = f"noise before\n```json\nOutput: Approve\ncorrelation_id: `{cid}`\n```\nmore noise"
    assert "Output: Approve" in a2a.extract_verdict(out, cid)
    assert "noise" not in a2a.extract_verdict(out, cid)
    tail = a2a.extract_verdict("nothing useful here at all", cid)
    assert len(tail) <= 1500


def test_trust_user_input_by_target(env):
    answered = {"status": "answered", "verdict": "Output: Approve", "correlation_id": "a2a-k1"}
    raven = a2a.apply_trust_policy("raven", "[USER INPUT]", dict(answered))
    assert "advisory-only" in raven["verdict"] and raven["status"] == "answered"
    iris = a2a.apply_trust_policy("iris", "[USER INPUT]", dict(answered))
    assert iris["status"] == "rejected" and "Output: Reject" in iris["verdict"]
    elena = a2a.apply_trust_policy("elena", "[USER INPUT]", dict(answered))
    assert "Output: Deny" in elena["verdict"]
    kai = a2a.apply_trust_policy("kai", "[USER INPUT]", dict(answered))
    assert kai["verdict"] == "Output: Approve"
    internal = a2a.apply_trust_policy("raven", "[INTERNAL]", dict(answered))
    assert internal["verdict"] == "Output: Approve"


def test_delegate_dry_run_registers_and_never_spawns(env, monkeypatch):
    def explode(*_a, **_k):
        raise AssertionError("dry-run must not spawn opencode")

    monkeypatch.setattr(a2a.subprocess, "run", explode)
    monkeypatch.setattr(a2a, "load_cards", lambda: CARDS)
    rec = a2a.delegate(
        "raven", "security review", "review the findings", dry_run=True, registry=env
    )
    assert rec["status"] == "dry-run" and "[A2A → Raven" in rec["request_block"]
    rows = a2a.registry_rows(env)
    assert [r["status"] for r in rows] == ["pending", "dry-run"]


def test_delegate_blocked_by_the_guard(env, monkeypatch):
    monkeypatch.setattr(a2a, "load_cards", lambda: CARDS)
    monkeypatch.setattr(
        "auto_guard.guard",
        lambda **_k: GuardResult(action="block", rule_id="rm_any"),
    )
    rec = a2a.delegate("raven", "security review", "rm -rf everything", registry=env)
    assert rec["ok"] is False and rec["guard"]["action"] == "block"
    assert rec["guard"]["rule"] == "rm_any" and "hint" in rec
    assert a2a.registry_rows(env)[-1]["status"] == "blocked"


def test_delegate_answers_with_the_extracted_verdict(env, monkeypatch, tmp_path):
    monkeypatch.setattr(a2a, "load_cards", lambda: CARDS)
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    monkeypatch.setattr(a2a, "RUNS_DIR", tmp_path / "runs")
    cid = "a2a-verdict1"

    def fake_run(_cmd, **_k):
        out = f"plugin noise\n```json\nOutput: Approve\ncorrelation_id: `{cid}`\n```"
        return subprocess.CompletedProcess(_cmd, 0, stdout=out, stderr="")

    monkeypatch.setattr(a2a.subprocess, "run", fake_run)
    rec = a2a.delegate("raven", "security review", "review it", cid=cid, registry=env)
    assert rec["status"] == "answered" and "Output: Approve" in rec["verdict"]
    assert rec["returncode"] == 0
    assert Path(rec["run_log"]).exists()
    assert a2a.registry_rows(env)[-1]["status"] == "answered"


def test_delegate_turns_a_dead_run_into_an_error(env, monkeypatch):
    monkeypatch.setattr(a2a, "load_cards", lambda: CARDS)
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))

    def dead_run(_cmd, **_k):
        return subprocess.CompletedProcess(_cmd, 3, stdout="traceback", stderr="boom")

    monkeypatch.setattr(a2a.subprocess, "run", dead_run)
    rec = a2a.delegate("kai", "automation", "do a thing", registry=env)
    assert rec["status"] == "error" and "rc=3" in rec["verdict"]


def test_delegate_reports_a_timeout(env, monkeypatch):
    monkeypatch.setattr(a2a, "load_cards", lambda: CARDS)
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    monkeypatch.setattr(
        a2a.subprocess,
        "run",
        lambda *_a, **_k: (_ for _ in ()).throw(subprocess.TimeoutExpired("opencode", 300)),
    )
    rec = a2a.delegate("kai", "automation", "do a thing", registry=env)
    assert rec["status"] == "error" and "timeout after 300s" in rec["verdict"]


def test_delegate_survives_a_missing_opencode(env, monkeypatch):
    monkeypatch.setattr(a2a, "load_cards", lambda: CARDS)
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    monkeypatch.setattr(
        a2a.subprocess, "run", lambda *_a, **_k: (_ for _ in ()).throw(OSError("no binary"))
    )
    rec = a2a.delegate("kai", "automation", "do a thing", registry=env)
    assert rec["status"] == "error" and "opencode run failed" in rec["verdict"]


def test_send_opencode_wraps_and_posts_the_prompt(env, monkeypatch):
    now = time.time() * 1000
    calls = []

    def fake_http(method, url, payload=None):
        calls.append((method, url, payload))
        if url.rstrip("/").endswith("/session"):
            return 200, {
                "data": [
                    {
                        "id": "ses_1",
                        "slug": "main",
                        "title": "the human session",
                        "time": {"updated": now},
                        "tokens": {"input": 99, "output": 1},
                    }
                ],
                "cursor": None,
            }
        return 200, {}

    rec = a2a.send("opencode", "hello session", _http=fake_http, registry=env)
    assert rec["ok"] is True and rec["status"] == "sent"
    method, url, payload = calls[-1]
    assert method == "POST" and url.endswith("/session/ses_1/prompt")
    body = payload["text"]
    assert "<<<A2A-" in body and "A2A-" in body and "[A2A · message from" in body
    assert a2a.registry_rows(env)[-1]["status"] == "sent"


def test_send_opencode_reports_a_dead_server(env):
    def dead(_method, _url, _payload=None):
        raise RuntimeError("connection refused")

    rec = a2a.send("opencode", "hi", _http=dead, registry=env)
    assert rec["ok"] is False and "does not answer" in rec["error"]


def test_send_rejects_unknown_targets_and_empty_messages(env):
    assert "unknown target" in a2a.send("persona", "hi", registry=env)["error"]
    assert "empty message" in a2a.send("opencode", "  ", registry=env)["error"]


def test_send_claude_queues_on_the_bus_for_the_newest_cursor(env, monkeypatch):
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    cursor = a2a.CURSORS_DIR / "a2a-workspace-sesA.json"
    cursor.write_text(json.dumps({"ts": time.time(), "sid": "sesA"}))
    rec = a2a.send("claude", "wake up", registry=env)
    assert rec["ok"] is True and rec["status"] == "queued" and rec["session"] == "sesA"
    events = [json.loads(l) for l in a2a.BUS.read_text().splitlines()]
    assert events[0]["kind"] == "a2a" and events[0]["to"] == "claude:sesA"
    assert a2a.registry_rows(env)[-1]["status"] == "queued"


def test_send_claude_rejects_oversized_and_unknown_sessions(env, monkeypatch):
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    big = a2a.send("claude", "x" * (a2a.A2A_MSG_MAX + 1), registry=env)
    assert "split it" in big["error"]
    rec = a2a.send("claude", "hi", session="ghost", registry=env)
    assert rec["ok"] is False and "no Claude session 'ghost'" in rec["error"]
    none = a2a.send("claude", "hi", registry=env)
    assert "no Claude sessions with hooks" in none["error"]


def test_show_list_cancel_and_reap(env, monkeypatch):
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    rec = a2a.delegate("raven", "security review", "review it", dry_run=True, registry=env)
    cid = rec["correlation_id"]
    assert a2a.show("missing", registry=env)["Output"] == "NotFound"
    assert "dry-run" in json.dumps(a2a.list_tasks(registry=env))
    assert a2a.cancel(cid, registry=env)["Output"] == "Canceled"
    assert a2a.cancel(cid, registry=env)["Output"] == "AlreadyTerminal"
    assert a2a.show(cid, registry=env)["status"] == "canceled"
    old = {"ts": time.time() - 100 * 3600, "correlation_id": "a2a-old1", "status": "queued"}
    a2a._registry_append(old, env)
    reaped = a2a.reap(stale_h=48, registry=env)
    assert [r["correlation_id"] for r in reaped] == ["a2a-old1"]
    assert a2a.show("a2a-old1", registry=env)["status"] == "canceled"


def test_the_cli_roundtrip(env, monkeypatch, capsys):
    monkeypatch.setattr("auto_guard.guard", lambda **_k: GuardResult(action="allow"))
    rec = a2a.delegate("kai", "automation", "do a thing", dry_run=True, registry=env)
    cid = rec["correlation_id"]
    assert a2a.main(["list", "--status", "dry-run"]) == 0
    assert "dry-run" in capsys.readouterr().out
    assert a2a.main(["show", cid]) == 0
    assert cid in capsys.readouterr().out
    assert a2a.main(["show", "missing", "--json"]) == 1
    assert a2a.main(["cancel", cid]) == 0
