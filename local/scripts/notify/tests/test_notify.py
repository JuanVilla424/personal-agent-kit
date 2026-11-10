"""Tests for notify.py — Slack webhook + task ledger. No real network/FS side effects:
TASKS_FILE is redirected to a tmp path and the webhook/urllib layer is mocked.
"""

import datetime
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import notify as nt  # noqa: E402


@pytest.fixture
def tf(tmp_path, monkeypatch):
    f = tmp_path / "tasks.json"
    monkeypatch.setattr(nt, "TASKS_FILE", f)
    monkeypatch.delenv("NOTIFY_SILENT", raising=False)
    return f


class TestTaskLedger:
    def test_load_empty_when_no_file(self, tf):
        assert nt._load_tasks() == []

    def test_save_load_roundtrip(self, tf):
        nt._save_tasks([{"id": 1, "title": "x", "status": "pending"}])
        assert nt._load_tasks()[0]["id"] == 1

    def test_task_add_assigns_incrementing_ids(self, tf):
        with patch.object(nt, "notify", return_value=True) as n:
            nt.task_add("ACC", "res", "do thing")
            nt.task_add("ACC", "res2", "do other")
        assert [t["id"] for t in nt._load_tasks()] == [1, 2]
        assert n.called

    def test_task_update_changes_status_and_result(self, tf):
        nt._save_tasks([{"id": 1, "title": "x", "status": "pending"}])
        with patch.object(nt, "notify", return_value=True):
            nt.task_update(1, "in_progress", "working")
        t = nt._load_tasks()[0]
        assert t["status"] == "in_progress" and t["result"] == "working"

    def test_task_update_completed_removes(self, tf):
        nt._save_tasks([{"id": 1, "title": "x", "status": "pending"}])
        with patch.object(nt, "notify", return_value=True):
            nt.task_update(1, "completed")
        assert nt._load_tasks() == []

    def test_task_meta_sets_account_and_resource(self, tf):
        nt._save_tasks([{"id": 1, "title": "x", "status": "pending"}])
        with patch.object(nt, "notify", return_value=True):
            nt.task_meta(1, "ACC", "res")
        t = nt._load_tasks()[0]
        assert t["account"] == "ACC" and t["resource"] == "res"

    def test_task_delete(self, tf):
        nt._save_tasks([{"id": 1, "title": "x", "status": "pending"}])
        with patch.object(nt, "notify", return_value=True):
            nt.task_delete(1)
        assert nt._load_tasks() == []

    def test_task_list_prints(self, tf, capsys):
        nt._save_tasks(
            [
                {
                    "id": 3,
                    "title": "hello",
                    "status": "pending",
                    "account": "A",
                    "resource": "R",
                    "result": "done",
                }
            ]
        )
        nt.task_list()
        out = capsys.readouterr().out
        assert "#3" in out and "hello" in out

    def test_task_list_empty(self, tf, capsys):
        nt.task_list()
        assert "No tasks" in capsys.readouterr().out


class TestSendTasks:
    def test_silent_returns_true(self, tf, monkeypatch):
        monkeypatch.setenv("NOTIFY_SILENT", "1")
        assert nt.send_tasks() is True

    def test_no_tasks_returns_false(self, tf):
        assert nt.send_tasks() is False

    def test_with_failed_task_alerts(self, tf):
        nt._save_tasks(
            [
                {
                    "id": 1,
                    "title": "x",
                    "status": "failed",
                    "account": "A",
                    "resource": "R",
                    "result": "boom",
                }
            ]
        )
        with patch.object(nt, "notify", return_value=True) as n:
            assert nt.send_tasks() is True
        assert n.call_args[0][2] == "alert"

    def test_refresh_runs_monitor_cmd(self, tf):
        nt._save_tasks(
            [
                {
                    "id": 1,
                    "title": "x",
                    "status": "pending",
                    "monitor_cmd": ["monitor.py", "--flag"],
                },
                {"id": 2, "title": "y", "status": "pending"},  # no monitor_cmd → skipped
            ]
        )
        with patch.object(nt.subprocess, "run") as run:
            nt._refresh_tasks()
        assert run.called


class TestWebhook:
    def test_bad_scheme_rejected(self):
        assert nt._send_webhook("ftp://x", b"{}") is False

    def test_success(self):
        resp = MagicMock(status=200)
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        with patch.object(nt.urllib.request, "urlopen", return_value=cm):
            assert nt._send_webhook("https://hooks", b"{}") is True

    def test_http_error(self):
        err = nt.urllib.error.HTTPError("https://x", 500, "err", {}, None)
        err.read = lambda: b"body"
        with patch.object(nt.urllib.request, "urlopen", side_effect=err):
            assert nt._send_webhook("https://x", b"{}") is False

    def test_generic_error(self):
        with patch.object(nt.urllib.request, "urlopen", side_effect=OSError("down")):
            assert nt._send_webhook("https://x", b"{}") is False


class TestPayloadAndNotify:
    NOW = datetime.datetime(2026, 6, 14, 12, 0, 0)

    def test_payload_with_fields(self):
        out = nt._slack_payload("T", "M", "alert", [{"name": "n", "value": "v"}], self.NOW)
        att = json.loads(out)["attachments"][0]
        assert "T" in att["title"]
        assert att["fields"][0]["title"] == "n"

    def test_payload_unknown_level_no_fields(self):
        att = json.loads(nt._slack_payload("T", "M", "weird", [], self.NOW))["attachments"][0]
        assert "fields" not in att

    def test_notify_without_url(self, monkeypatch):
        monkeypatch.setattr(nt, "SLACK_WEBHOOK_URL", None)
        assert nt.notify("t", "m") is False

    def test_notify_with_url_delegates(self, monkeypatch):
        monkeypatch.setattr(nt, "SLACK_WEBHOOK_URL", "https://hooks")
        with patch.object(nt, "_send_webhook", return_value=True) as w:
            assert nt.notify("t", "m", "info", fields=[{"name": "a", "value": "b"}]) is True
        assert w.called


class TestRouters:
    def test_agent_trigger(self):
        with patch.object(nt, "notify", return_value=True) as n:
            assert nt.notify_agent_trigger("Kai", "query", "q", "cid") is True
        assert "PAK→Kai" in n.call_args[0][0]

    def test_agent_generates_cid(self):
        with patch.object(nt, "notify", return_value=True) as n:
            nt.notify_agent("Raven", "query", "q")
        assert "PAK→Raven" in n.call_args[0][0]
