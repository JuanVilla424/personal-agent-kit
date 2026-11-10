"""Smoke tests for memory_service's auth hardening.

No real Qdrant or fastembed (lazy + mocks). Covers: identity-from-token (anti-IDOR),
admin, invalid token (401), no-auth mode, fail-closed on startup, and ownership in /forget."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastembed")
pytest.importorskip("qdrant_client")

MEM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MEM_DIR))
os.environ.setdefault("MEMORY_ALLOW_NO_AUTH", "true")  # get past the fail-closed check on import
import memory_service as ms  # noqa: E402


def test_parse_user_tokens():
    assert ms._parse_user_tokens("t1:juan,t2:maria") == {"t1": "juan", "t2": "maria"}
    assert ms._parse_user_tokens("") == {}
    assert ms._parse_user_tokens("nocolons") == {}
    assert ms._parse_user_tokens(" t1 : juan ") == {"t1": "juan"}  # strip


def test_resolve_uses_token_identity_not_client_field(monkeypatch):
    monkeypatch.setattr(ms, "USER_TOKENS", {"tok_juan": "juan"})
    monkeypatch.setattr(ms, "MEMORY_ADMIN_TOKEN", "")
    monkeypatch.setattr(ms, "ALLOW_NO_AUTH", False)
    user, is_admin = ms._resolve("tok_juan", claimed_user="hacker")
    assert user == "juan"  # token's own identity, NOT "hacker" → anti-IDOR
    assert is_admin is False


def test_resolve_admin_token(monkeypatch):
    monkeypatch.setattr(ms, "USER_TOKENS", {})
    monkeypatch.setattr(ms, "MEMORY_ADMIN_TOKEN", "tok_admin")
    monkeypatch.setattr(ms, "ALLOW_NO_AUTH", False)
    user, is_admin = ms._resolve("tok_admin", claimed_user="juan")
    assert is_admin is True


def test_resolve_invalid_token_401(monkeypatch):
    from fastapi import HTTPException

    monkeypatch.setattr(ms, "USER_TOKENS", {"tok_juan": "juan"})
    monkeypatch.setattr(ms, "MEMORY_ADMIN_TOKEN", "")
    monkeypatch.setattr(ms, "ALLOW_NO_AUTH", False)
    with pytest.raises(HTTPException) as exc:
        ms._resolve("WRONG")
    assert exc.value.status_code == 401


def test_resolve_no_auth_mode_trusts_claimed(monkeypatch):
    monkeypatch.setattr(ms, "USER_TOKENS", {})
    monkeypatch.setattr(ms, "MEMORY_ADMIN_TOKEN", "")
    monkeypatch.setattr(ms, "ALLOW_NO_AUTH", True)
    user, is_admin = ms._resolve("", claimed_user="juan")
    assert user == "juan" and is_admin is True


def test_fail_closed_without_auth_configured():
    # override=False → these explicit values win over the root .env; no auth → RuntimeError.
    code = "import sys; sys.path.insert(0, r'%s'); import memory_service" % str(MEM_DIR)
    env = dict(os.environ)
    env.update(
        {"MEMORY_ALLOW_NO_AUTH": "false", "MEMORY_USER_TOKENS": "", "MEMORY_ADMIN_TOKEN": ""}
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert r.returncode != 0
    assert "No auth configured" in r.stderr


def test_forget_ownership(monkeypatch):
    from fastapi.testclient import TestClient

    class FakePoint:
        def __init__(self, payload):
            self.payload = payload

    class FakeClient:
        def __init__(self, payload):
            self._payload = payload
            self.deleted = False

        def retrieve(self, *a, **k):
            return [FakePoint(self._payload)]

        def delete(self, *a, **k):
            self.deleted = True

    monkeypatch.setattr(ms, "USER_TOKENS", {"tok_juan": "juan"})
    monkeypatch.setattr(ms, "MEMORY_ADMIN_TOKEN", "tok_admin")
    monkeypatch.setattr(ms, "ALLOW_NO_AUTH", False)
    monkeypatch.setattr(ms, "_push_metrics", lambda: None)
    client = TestClient(ms.app)
    hdr = {"X-Memory-Token": "tok_juan"}

    # juan tries to delete another user's memory → 403
    monkeypatch.setattr(ms, "_client_get", lambda: FakeClient({"scope": "user", "user": "maria"}))
    assert client.post("/memory/forget", json={"id": "x"}, headers=hdr).status_code == 403

    # juan tries to delete a shared memory without being admin → 403
    monkeypatch.setattr(ms, "_client_get", lambda: FakeClient({"scope": "shared", "user": ""}))
    assert client.post("/memory/forget", json={"id": "x"}, headers=hdr).status_code == 403

    # juan deletes his own → 200
    monkeypatch.setattr(ms, "_client_get", lambda: FakeClient({"scope": "user", "user": "juan"}))
    assert client.post("/memory/forget", json={"id": "x"}, headers=hdr).status_code == 200
