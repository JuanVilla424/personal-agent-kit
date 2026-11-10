"""Branch coverage for security/permissions.py — config is injected via a patched
_load(), so no real permissions.yaml is read (except the two _load() tests)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from security import permissions as perm  # noqa: E402

CFG = {
    "defaults": {
        "allowed_tools": ["Read"],
        "budget_usd_per_query": 1.0,
        "models": ["m-default"],
        "mcp_enabled": True,
    },
    "roles": {
        "user": {"allowed_tools": ["Read"], "budget_usd_per_query": 1.0, "models": ["m-user"]},
        "admin": {
            "allowed_tools": ["Read", "Bash"],
            "budget_usd_per_query": 5.0,
            "models": ["m-admin"],
            "dangerous_tools_require_2fa": True,
            "bypass_quiet_hours": True,
        },
        "system": {
            "allowed_tools": ["Read", "Write"],
            "budget_usd_per_query": 2.0,
            "models": ["m-sys"],
        },
    },
    "users": {"42": {"role": "admin"}, "99": {"role": "blocked"}},
    "guilds": {"whitelist": ["g1"]},
    "channels": {"whitelist": ["c1"]},
    "quiet_hours": {
        "enabled": True,
        "timezone": "America/Bogota",
        "start": "22:00",
        "end": "06:00",
    },
}


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr(perm, "_load", lambda: CFG)
    return CFG


class TestCheck:
    def test_guild_not_whitelisted(self, cfg):
        d = perm.check("42", guild_id="other")
        assert d.allowed is False and d.reason == "guild_not_whitelisted"

    def test_channel_not_whitelisted(self, cfg):
        d = perm.check("42", channel_id="other", guild_id="g1")
        assert d.allowed is False and d.reason == "channel_not_whitelisted"

    def test_blocked_user(self, cfg):
        d = perm.check("99", guild_id="g1", channel_id="c1")
        assert d.allowed is False and d.role == "blocked"

    def test_admin_ok(self, cfg):
        d = perm.check("42", guild_id="g1", channel_id="c1", requested_locale="en")
        assert d.allowed and d.role == "admin"
        assert d.requires_2fa is True
        assert d.model == "m-admin" and d.locale == "en"

    def test_unknown_user_defaults_to_user(self, cfg):
        assert perm.check("777", guild_id="g1", channel_id="c1").role == "user"

    def test_no_whitelist_allows(self, monkeypatch):
        monkeypatch.setattr(perm, "_load", lambda: {"roles": {"user": {}}})
        assert perm.check("1").allowed is True


class TestDecisions:
    def test_system_decision(self, cfg):
        d = perm.system_decision()
        assert d.role == "system" and d.model == "m-sys"

    def test_needs_2fa_true(self, cfg):
        d = perm.check("42", guild_id="g1", channel_id="c1")
        assert perm.needs_2fa(d, ["Bash"]) is True

    def test_needs_2fa_false_when_not_required(self):
        d = perm.Decision(allowed=True, reason="ok", role="user")
        assert perm.needs_2fa(d, ["Bash"]) is False

    def test_needs_2fa_false_for_safe_tools(self, cfg):
        d = perm.check("42", guild_id="g1", channel_id="c1")
        assert perm.needs_2fa(d, ["Read"]) is False


class TestQuietHours:
    def test_disabled(self, monkeypatch):
        monkeypatch.setattr(perm, "_load", lambda: {"quiet_hours": {"enabled": False}})
        assert perm.is_quiet_hours("1") is False

    def test_bypass_role(self, cfg):
        assert perm.is_quiet_hours("42") is False  # admin bypasses

    def test_same_day_window_executes(self, monkeypatch):
        monkeypatch.setattr(
            perm,
            "_load",
            lambda: {
                "quiet_hours": {
                    "enabled": True,
                    "timezone": "America/Bogota",
                    "start": "00:00",
                    "end": "23:59",
                },
                "roles": {"user": {}},
                "users": {},
            },
        )
        assert isinstance(perm.is_quiet_hours("1"), bool)

    def test_overnight_window_executes(self, monkeypatch):
        monkeypatch.setattr(
            perm,
            "_load",
            lambda: {
                "quiet_hours": {
                    "enabled": True,
                    "timezone": "America/Bogota",
                    "start": "22:00",
                    "end": "06:00",
                },
                "roles": {"user": {}},
                "users": {},
            },
        )
        assert isinstance(perm.is_quiet_hours("1"), bool)

    def test_invalid_config_returns_false(self, monkeypatch):
        monkeypatch.setattr(
            perm,
            "_load",
            lambda: {
                "quiet_hours": {"enabled": True, "start": "bad"},
                "roles": {"user": {}},
                "users": {},
            },
        )
        assert perm.is_quiet_hours("1") is False


class TestLoad:
    def test_reads_yaml(self, tmp_path, monkeypatch):
        f = tmp_path / "permissions.yaml"
        f.write_text("roles:\n  user:\n    allowed_tools: [Read]\n")
        monkeypatch.setattr(perm, "_YAML_PATH", f)
        monkeypatch.setattr(perm, "_cache", {})
        monkeypatch.setattr(perm, "_cache_ts", 0.0)
        assert "roles" in perm._load()

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(perm, "_YAML_PATH", tmp_path / "nope.yaml")
        monkeypatch.setattr(perm, "_cache", {})
        monkeypatch.setattr(perm, "_cache_ts", 0.0)
        assert perm._load() == {}
