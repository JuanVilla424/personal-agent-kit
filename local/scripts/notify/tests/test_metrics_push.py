import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ops import metrics_push


def test_grouping_path_sanitizes_slashes():
    path = metrics_push._grouping_path("finops", {"host": "H1", "resource": "a/b c"})
    assert path == "job/finops/host/H1/resource/a_b%20c"


def test_build_grouping_uppercases_account(monkeypatch):
    monkeypatch.setenv("PAK_INVOKED_BY", "tester")
    grouping = metrics_push._build_grouping(account="acctfoo", extra_grouping={"suite": "DEI"})
    assert grouping["account"] == "ACCTFOO"
    assert grouping["invoked_by"] == "tester"
    assert grouping["suite"] == "DEI"
    assert grouping["host"]


def test_push_run_returns_false_on_unreachable_gateway(monkeypatch):
    monkeypatch.setattr(metrics_push, "PUSHGATEWAY_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(metrics_push, "PUSH_TIMEOUT_SECONDS", 1)
    assert metrics_push.push_run("smoke_test", duration_seconds=0.1) is False


def test_push_run_uses_stdlib_fallback_without_prometheus_client(monkeypatch):
    calls = {}

    def fake_push_text(job, grouping, gauges):
        calls["job"] = job
        calls["gauges"] = gauges
        return True

    monkeypatch.setattr(metrics_push, "_HAVE_PROMETHEUS_CLIENT", False)
    monkeypatch.setattr(metrics_push, "_push_text", fake_push_text)

    assert (
        metrics_push.push_run("waf_patch", account="ACCTFOO", waf_patch_rules_applied=15.0) is True
    )
    assert calls["job"] == "waf_patch"
    assert "waf_patch_last_run_timestamp_seconds" in calls["gauges"]
    assert calls["gauges"]["waf_patch_last_run_success"] == 1
    assert calls["gauges"]["waf_patch_rules_applied"] == 15.0


def test_registry_api_requires_prometheus_client(monkeypatch):
    monkeypatch.setattr(metrics_push, "_HAVE_PROMETHEUS_CLIENT", False)
    try:
        metrics_push.new_registry()
        raised = False
    except RuntimeError:
        raised = True
    assert raised
    assert metrics_push.push("job", registry=None) is False
