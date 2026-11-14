"""a2a.py's CLI, the OpenCode API bridge and the emitter identity — all hermetic."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "local" / "scripts" / "a2a"))

import a2a  # noqa: E402


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    reg = tmp_path / "a2a.jsonl"
    monkeypatch.setattr(a2a, "REGISTRY", reg)
    monkeypatch.setattr(a2a, "RUNS_DIR", tmp_path / "runs")
    return reg


def test_api_args_for_the_three_calls():
    listing = a2a._api_args("GET", "/session")
    assert listing == ["session.list", "--param", "limit=50"]
    paged = a2a._api_args("GET", "/session?cursor=c9")
    assert paged == ["session.list", "--param", "limit=50", "--param", "cursor=c9"]
    served = a2a._api_args("GET", "http://127.0.0.1:4096/session?cursor=c1")
    assert served == [
        "session.list",
        "--param",
        "limit=50",
        "--param",
        "cursor=c1",
        "--server",
        "http://127.0.0.1:4096",
    ]
    prompt = a2a._api_args("POST", "/session/ses_1/prompt", {"text": "hi"})
    assert prompt[:3] == ["session.prompt", "--param", "sessionID=ses_1"]
    assert json.loads(prompt[4]) == {"text": "hi"}
    with pytest.raises(ValueError):
        a2a._api_args("GET", "/collections")


def test_env_file_value(tmp_path):
    env_file = tmp_path / "env"
    env_file.write_text('OPENCODE_PASSWORD="s3cret"\nOTHER=x\n')
    assert a2a._env_file_value("OPENCODE_PASSWORD", env_file) == "s3cret"
    assert a2a._env_file_value("MISSING", env_file) == ""
    assert a2a._env_file_value("ANY", tmp_path / "nope") == ""


def test_http_json_parses_and_injects_the_password(tmp_path, monkeypatch):
    seen = {}

    def fake_run(cmd, capture_output, text, timeout, env):
        seen["cmd"] = cmd
        seen["env_password"] = env.get("OPENCODE_PASSWORD")
        return subprocess.CompletedProcess(cmd, 0, stdout='{"ok": true}', stderr="")

    env_file = tmp_path / "env"
    env_file.write_text("OPENCODE_PASSWORD=fromfile\n")
    monkeypatch.setattr(a2a, "OPENCODE_ENV_FILE", env_file)
    monkeypatch.setattr(a2a, "OPENCODE_BIN", "opencode-fake")
    monkeypatch.delenv("OPENCODE_PASSWORD", raising=False)
    monkeypatch.setattr(a2a.subprocess, "run", fake_run)
    # --server present → the password must be injected from the env file
    status, body = a2a._http_json("GET", "http://127.0.0.1:4096/session")
    assert status == 200 and body == {"ok": True}
    assert seen["cmd"][0] == "opencode-fake" and seen["env_password"] == "fromfile"

    def failing(cmd, **_k):
        return subprocess.CompletedProcess(cmd, 3, stdout="", stderr="server down")

    monkeypatch.setattr(a2a.subprocess, "run", failing)
    try:
        a2a._http_json("GET", "/session")
        raise AssertionError("should have raised")
    except RuntimeError as e:
        assert "server down" in str(e)


def test_sessions_pagination_stops_on_old_pages(monkeypatch):
    now_ms = time.time() * 1000
    pages = [
        {
            "data": [{"id": "fresh", "time": {"updated": now_ms}, "tokens": {"input": 1}}],
            "cursor": {"next": "c2"},
        },
        {
            "data": [{"id": "old", "time": {"updated": now_ms - 10 * 3600 * 1000}, "tokens": {}}],
            "cursor": None,
        },
    ]

    def fake_http(_m, url, _p=None):
        cursor = "c2" if "cursor=c2" in url else None
        return 200, pages[0] if cursor is None else pages[1]

    rows = a2a.opencode_sessions("http://x", _http=fake_http, pages=3)
    assert [r["id"] for r in rows] == ["fresh", "old"]


def test_sessions_accepts_the_legacy_bare_list(monkeypatch):
    rows = a2a.opencode_sessions(
        "", _http=lambda *_a, **_k: (200, [{"id": "l1", "time": {"updated": 1}}])
    )
    assert rows[0]["id"] == "l1"


def test_pick_live_session_prefers_tokens_within_the_window(monkeypatch):
    now = time.time() * 1000
    sessions = [
        {"id": "one-shot", "updated": now, "tokens": 3},
        {"id": "human", "updated": now - 3600 * 1000, "tokens": 999},
        {"id": "ancient", "updated": now - 40 * 3600 * 1000, "tokens": 9999},
    ]
    assert a2a.pick_live_session(sessions)["id"] == "human"
    assert a2a.pick_live_session(sessions, wanted="ancient")["id"] == "ancient"
    assert a2a.pick_live_session(sessions, wanted="nope") is None


def test_default_emitter_identity_chain(monkeypatch):
    for var in ("A2A_EMITTER", "OPENCODE_SESSION_ID", "BRAIN_ORIGIN"):
        monkeypatch.delenv(var, raising=False)
    assert a2a.default_emitter() == "orchestrator"
    monkeypatch.setenv("BRAIN_ORIGIN", "nightly")
    assert a2a.default_emitter() == "autonomous:nightly"
    monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_oc")
    assert a2a.default_emitter() == "opencode:ses_oc"
    monkeypatch.setenv("A2A_EMITTER", "party:raven")
    assert a2a.default_emitter() == "party:raven"


def test_save_run_survives_an_unwritable_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(a2a, "RUNS_DIR", tmp_path / "file-not-dir")
    (tmp_path / "file-not-dir").write_text("block")
    assert a2a._save_run("cid", ["opencode"], "out", "err") == ""


def test_cli_send_and_delegate_dispatch(registry, monkeypatch, capsys):
    called = []
    monkeypatch.setattr(a2a, "send", lambda *a, **k: called.append(("send", a, k)) or {"ok": True})
    assert a2a.main(["send", "opencode", "hello", "--trust", "USER"]) == 0
    assert called[-1][1] == ("opencode", "hello")
    assert called[-1][2]["trust"] == "USER"
    monkeypatch.setattr(
        a2a,
        "delegate",
        lambda *a, **k: called.append(("delegate", a))
        or {"status": "answered", "correlation_id": "c"},
    )
    assert a2a.main(["delegate", "raven", "security review", "task"]) == 0
    assert called[-1][1][:3] == ("raven", "security review", "task")


def test_cli_sessions_engines(registry, monkeypatch, capsys, tmp_path):
    from datetime import datetime

    monkeypatch.setattr(
        a2a,
        "opencode_sessions",
        lambda *a, **k: [{"id": "s1", "slug": "main", "tokens": 5, "title": "t", "updated": 1}],
    )
    monkeypatch.setattr(a2a, "pick_live_session", lambda rows, wanted="": rows[0])
    assert a2a.main(["sessions"]) == 0
    assert "s1" in capsys.readouterr().out
    cursor = tmp_path / "a2a-workspace-live.json"
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text("{}")
    os_utime_old = cursor.stat().st_mtime
    monkeypatch.setattr(a2a, "CURSORS_DIR", tmp_path)
    monkeypatch.setattr(
        "local.scripts.a2a.a2a.claude_sessions",
        lambda: [{"id": "live", "last_active": os_utime_old}],
        raising=False,
    )
    assert a2a.main(["sessions", "--engine", "claude"]) == 0
    assert "live" in capsys.readouterr().out
    assert datetime is not None


def test_cli_show_raw_reads_the_run_log(registry, tmp_path, capsys):
    run_log = tmp_path / "runs" / "a2a-raw1.log"
    run_log.parent.mkdir(parents=True)
    run_log.write_text("$ opencode\n--- stdout ---\nfull output")
    a2a._registry_append(
        {
            "ts": time.time(),
            "correlation_id": "a2a-raw1",
            "status": "answered",
            "receiver": "raven",
            "intent": "security review",
            "verdict": "Output: Approve",
            "run_log": str(run_log),
        },
        registry,
    )
    assert a2a.main(["show", "a2a-raw1", "--raw"]) == 0
    out = capsys.readouterr().out
    assert "full output" in out and "Output: Approve" in out
    assert a2a.main(["show", "a2a-raw1", "--json"]) == 0


def test_cli_reap_prints_the_report(registry, capsys):
    a2a._registry_append(
        {"ts": time.time() - 100 * 3600, "correlation_id": "a2a-stale", "status": "pending"},
        registry,
    )
    assert a2a.main(["reap", "--dry-run"]) == 0
    assert "a2a-stale" in capsys.readouterr().out


def test_cli_unknown_command_is_argparse_error(registry):
    with pytest.raises(SystemExit) as e:
        a2a.main(["teleport"])
    assert e.value.code == 2


def test_registry_append_is_atomic_and_ordered(registry):
    a2a._registry_append({"n": 1}, registry)
    a2a._registry_append({"n": 2}, registry)
    rows = a2a.registry_rows(registry)
    assert [r["n"] for r in rows] == [1, 2]
    assert a2a.registry_rows(tmp_missing()) == []


def tmp_missing():
    from pathlib import Path as _P

    return _P("/nonexistent/registry.jsonl")
