"""Coverage for small notify helpers: tracing, sandbox, thread_manager,
two_factor, and the root stream_parser (Anthropic event format)."""

import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

NOTIFY = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(NOTIFY))

import stream_parser as sp2  # noqa: E402  (root notify/stream_parser.py, not core/)
from core import sandbox as sb  # noqa: E402
from core import thread_manager as tm  # noqa: E402
from core import tracing as tr  # noqa: E402
from security import two_factor as tf  # noqa: E402


class TestTracing:
    def test_new_get_set(self):
        rid = tr.new_request_id()
        assert len(rid) == 12 and tr.get_request_id() == rid
        tr.set_request_id("abc")
        assert tr.get_request_id() == "abc"


class TestSandbox:
    def test_disabled(self, monkeypatch):
        monkeypatch.setenv("SANDBOX_DISABLED", "1")
        assert sb.wrap_cmd(["echo"], "/repo") == ["echo"]

    def test_no_firejail(self, monkeypatch):
        monkeypatch.delenv("SANDBOX_DISABLED", raising=False)
        monkeypatch.setattr(sb.shutil, "which", lambda x: None)
        assert sb.wrap_cmd(["echo"], "/repo") == ["echo"]

    def test_wrapped(self, monkeypatch):
        monkeypatch.delenv("SANDBOX_DISABLED", raising=False)
        monkeypatch.setattr(sb.shutil, "which", lambda x: "/usr/bin/firejail")
        out = sb.wrap_cmd(["echo", "hi"], "/repo")
        assert out[0] == "firejail" and out[-2:] == ["echo", "hi"]


class TestThreadManager:
    def test_queue_ops(self):
        q = tm.get_queue("t1")
        assert tm.queue_size("t1") == 0
        q.put_nowait("x")
        assert tm.queue_size("t1") == 1
        assert tm.total_queue_depth() >= 1
        assert tm.queue_size("unknown") == 0
        assert tm.active_thread_count() == 0
        tm.cleanup_idle()

    async def test_worker_register_and_cleanup(self):
        import asyncio

        async def noop():
            return None

        task = asyncio.ensure_future(noop())
        tm.register_worker("tw", task)
        await task
        await asyncio.sleep(0)  # let the done-callbacks run before judging the registry
        assert tm.active_thread_count() == 0
        # stale on ANY machine: monotonic() is seconds-since-boot, and a fresh CI runner
        # boots with it under _IDLE_CLEANUP_SECS — a literal 0.0 only looked stale on
        # long-uptime boxes (the 13/11 CI red)
        tm._last_activity["tw"] = time.monotonic() - 601
        tm.cleanup_idle()
        assert "tw" not in tm._workers


class TestTwoFactor:
    def test_disabled_allows(self, monkeypatch):
        monkeypatch.setattr(tf, "_PYOTP_OK", False)
        assert tf.verify("u", "123") is True

    def test_no_secret_allows(self, monkeypatch):
        monkeypatch.setattr(tf, "_PYOTP_OK", True)
        monkeypatch.setattr(tf, "_SECRETS", {})
        assert tf.verify("u", "1") is True

    def test_verify_with_secret(self, monkeypatch):
        monkeypatch.setattr(tf, "_PYOTP_OK", True)
        monkeypatch.setattr(tf, "_SECRETS", {"u": "S"})
        totp = MagicMock()
        totp.verify.return_value = True
        monkeypatch.setattr(
            tf, "pyotp", MagicMock(TOTP=MagicMock(return_value=totp)), raising=False
        )
        assert tf.verify("u", "000") is True

    def test_verify_error(self, monkeypatch):
        monkeypatch.setattr(tf, "_PYOTP_OK", True)
        monkeypatch.setattr(tf, "_SECRETS", {"u": "S"})
        monkeypatch.setattr(
            tf, "pyotp", MagicMock(TOTP=MagicMock(side_effect=ValueError("x"))), raising=False
        )
        assert tf.verify("u", "000") is False

    def test_has_secret(self, monkeypatch):
        monkeypatch.setattr(tf, "_SECRETS", {"u": "s"})
        assert tf.has_secret("u") is True and tf.has_secret("z") is False

    def test_load_secrets(self, tmp_path, monkeypatch):
        f = tmp_path / "totp.secrets"
        f.write_text("# c\nu1 = SEC1\nbadline\nu2=SEC2\n")
        monkeypatch.setattr(tf, "_TOTP_KEY_FILE", f)
        monkeypatch.setattr(tf, "_SECRETS", {})
        tf._load_secrets()
        assert tf._SECRETS == {"u1": "SEC1", "u2": "SEC2"}

    def test_load_secrets_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tf, "_TOTP_KEY_FILE", tmp_path / "none")
        monkeypatch.setattr(tf, "_SECRETS", {})
        tf._load_secrets()
        assert tf._SECRETS == {}


class TestStreamParserRoot:
    def test_text_delta(self):
        assert (
            sp2.extract_text_delta(
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}
            )
            == "hi"
        )
        assert sp2.extract_text_delta({"type": "x"}) == ""
        assert (
            sp2.extract_text_delta({"type": "content_block_delta", "delta": {"type": "other"}})
            == ""
        )

    def test_tool_name(self):
        assert (
            sp2.extract_tool_name(
                {
                    "type": "content_block_start",
                    "content_block": {"type": "tool_use", "name": "Read"},
                }
            )
            == "Read"
        )
        assert sp2.extract_tool_name({"type": "x"}) is None
        assert (
            sp2.extract_tool_name(
                {"type": "content_block_start", "content_block": {"type": "text"}}
            )
            is None
        )

    def test_is_final(self):
        assert sp2.is_final({"type": "message_stop"}) is True
        assert sp2.is_final({"type": "x"}) is False

    async def test_stream_events(self):
        async def gen():
            for line in [b'{"a": 1}\n', b"\n", b"bad\n"]:
                yield line

        assert [e async for e in sp2.stream_events(gen())] == [{"a": 1}]
