"""Failure paths of the security modules: broken input must not open a gate, lose a rule or crash."""

import datetime
import io
import json
import logging
import sys
import types
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.i18n import t  # noqa: E402
from ops import metrics_push as mp  # noqa: E402
from security import anomaly_detector as ad  # noqa: E402
from security import audit_log as al  # noqa: E402
from security import content_filter as cf  # noqa: E402
from security import token_rotator as trot  # noqa: E402
from security import two_factor as tf  # noqa: E402
from ui import attachment_handler as ah  # noqa: E402


@pytest.fixture
def filter_config(tmp_path, monkeypatch):
    """Point the content filter at a scratch config and force the next scan to reload it."""
    path = tmp_path / "permissions.yaml"
    monkeypatch.setattr(cf, "_YAML_PATH", path)
    monkeypatch.setattr(cf, "_cache_ts", -cf._RELOAD_INTERVAL * 1e6)
    monkeypatch.setattr(cf, "_rules", [])
    monkeypatch.setattr(cf, "_enabled", True)
    return path


class TestContentFilter:
    def test_disabled_filter_lets_a_matching_text_through(self, filter_config):
        filter_config.write_text(
            "content_filter:\n  enabled: false\n  rules:\n    - {id: a, pattern: secret}\n",
            encoding="utf-8",
        )
        assert cf.scan("the secret").verdict == cf.Verdict.ALLOW

    def test_rule_without_pattern_does_not_stop_the_next_rule(self, filter_config):
        filter_config.write_text(
            "content_filter:\n  rules:\n    - {id: empty}\n    - {id: real, pattern: secret}\n",
            encoding="utf-8",
        )
        result = cf.scan("the secret")
        assert result.verdict == cf.Verdict.BLOCK
        assert result.rule_id == "real"

    def test_invalid_regex_does_not_stop_the_next_rule(self, filter_config):
        filter_config.write_text(
            "content_filter:\n  rules:\n"
            "    - {id: broken, pattern: '('}\n"
            "    - {id: real, pattern: secret}\n",
            encoding="utf-8",
        )
        assert cf.scan("the secret").rule_id == "real"

    def test_failed_reload_keeps_the_rules_already_loaded(self, filter_config, monkeypatch, caplog):
        monkeypatch.setattr(cf, "_rules", [{"id": "kept", "pattern": "secret"}])

        with caplog.at_level(logging.WARNING, logger="content-filter"):
            result = cf.scan("the secret")

        assert result.rule_id == "kept"
        assert "reload failed" in caplog.text


@pytest.fixture
def audit_dir(tmp_path, monkeypatch):
    directory = tmp_path / "audit"
    monkeypatch.setattr(al, "_AUDIT_DIR", directory)
    monkeypatch.setattr(al, "_prev_hash", {})
    return directory


def _today_log(directory: Path) -> Path:
    return directory / f"{datetime.date.today().isoformat()}.jsonl"


class TestAuditLog:
    async def test_write_failure_is_logged_and_never_raises(self, audit_dir, caplog):
        _today_log(audit_dir).mkdir(parents=True)  # opening a directory for append fails

        with caplog.at_level(logging.ERROR, logger="audit"):
            await al.write("event", user_id="u1")

        assert "Audit write failed" in caplog.text

    async def test_verify_defaults_to_today(self, audit_dir):
        await al.write("event", user_id="u1")
        assert al.verify_chain() is True

    def test_a_day_without_log_has_nothing_to_contradict(self, audit_dir):
        assert al.verify_chain("2001-01-01") is True

    async def test_blank_lines_do_not_break_the_chain(self, audit_dir):
        await al.write("event", user_id="u1")
        path = _today_log(audit_dir)
        path.chmod(0o640)
        path.write_text(path.read_text(encoding="utf-8") + "\n\n", encoding="utf-8")
        assert al.verify_chain() is True

    async def test_corrupt_line_fails_the_chain(self, audit_dir):
        await al.write("event", user_id="u1")
        path = _today_log(audit_dir)
        path.chmod(0o640)
        path.write_text(path.read_text(encoding="utf-8") + "{not json\n", encoding="utf-8")
        assert al.verify_chain() is False

    async def test_removing_the_first_entry_fails_the_chain(self, audit_dir):
        await al.write("first", user_id="u1")
        await al.write("second", user_id="u1")
        path = _today_log(audit_dir)
        path.chmod(0o640)
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        assert json.loads(lines[1])["event"] == "second"
        path.write_text(lines[1], encoding="utf-8")
        assert al.verify_chain() is False


def _failing_notify(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("slack is down")

    monkeypatch.setitem(sys.modules, "notify", types.SimpleNamespace(notify=boom))


class TestAlertsNeverBreakTheCaller:
    async def test_anomaly_alert_survives_a_notify_failure(self, monkeypatch, caplog):
        _failing_notify(monkeypatch)

        with caplog.at_level(logging.WARNING, logger=ad.log.name):
            await ad.alert("u1", "text")

        assert "Anomaly alert failed" in caplog.text

    def test_token_alert_survives_a_notify_failure(self, monkeypatch):
        _failing_notify(monkeypatch)
        assert trot._alert("expired") is None


class TestTwoFactor:
    def test_unreadable_secrets_file_loads_no_secret(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(tf, "_TOTP_KEY_FILE", tmp_path)  # a directory cannot be opened
        monkeypatch.setattr(tf, "_SECRETS", {})

        with caplog.at_level(logging.WARNING, logger="2fa"):
            tf._load_secrets()

        assert tf._SECRETS == {}
        assert "TOTP secrets load failed" in caplog.text


class TestRootEnvValue:
    def test_reads_the_key_past_comments_blanks_and_quotes(self, tmp_path, monkeypatch):
        (tmp_path / ".env").write_text(
            '# comment\n\nOTHER=1\nnot a pair\nPUSHGATEWAY_URL="http://gw:1"\n', encoding="utf-8"
        )
        monkeypatch.setattr(mp, "REPO_ROOT", str(tmp_path))
        assert mp._root_env_value("PUSHGATEWAY_URL") == "http://gw:1"
        assert mp._root_env_value("MISSING") == ""

    def test_missing_env_file_reads_as_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mp, "REPO_ROOT", str(tmp_path))
        assert mp._root_env_value("PUSHGATEWAY_URL") == ""


class TestPushFailures:
    def test_a_missing_pushgateway_warns_once(self, monkeypatch, caplog):
        def refused(*_args, **_kwargs):
            raise OSError("connection refused")

        monkeypatch.setattr(mp, "_HAVE_PROMETHEUS_CLIENT", True)
        monkeypatch.setattr(mp, "push_to_gateway", refused, raising=False)
        monkeypatch.setattr(mp, "_push_failure_logged", False)

        with caplog.at_level(logging.WARNING, logger="metrics-push"):
            assert mp.push("job", None) is False
            assert mp.push("job", None) is False

        assert caplog.text.count("metrics push to") == 1


class TestAttachments:
    def test_pdf_text_is_extracted_from_a_real_pdf(self):
        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        pdf.drawString(72, 720, "quarterly numbers")
        pdf.save()

        assert "quarterly numbers" in ah._pdf_text(buffer.getvalue())


class TestI18n:
    def test_missing_placeholder_value_returns_the_template(self):
        assert t("processing", locale="en", unrelated="x") == t("processing", locale="en")

    def test_template_with_an_unfilled_placeholder_stays_readable(self, monkeypatch):
        from core import i18n

        monkeypatch.setitem(i18n._STRINGS, "greeting", {"en": "Hello {name}"})
        assert t("greeting", locale="en", other="x") == "Hello {name}"
