"""Coverage for notify/bot.py — Slack bot. slack_bolt AsyncApp is faked, every external
side effect (subprocess spawn, Slack client, sessions, cache, claude stream) is mocked."""

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("SLACK_BOT_TOKEN", "xoxb-test")
os.environ.setdefault("SLACK_APP_TOKEN", "xapp-test")

pytest.importorskip("slack_bolt")
sys.path.insert(0, str(Path(__file__).parent.parent))

import bot  # noqa: E402


class FakeApp:
    def __init__(self, *a, **k):
        self.actions, self.events, self.commands = {}, {}, {}
        self.client = MagicMock()

    def action(self, n):
        def d(f):
            self.actions[n] = f
            return f

        return d

    def event(self, n):
        def d(f):
            self.events.setdefault(n, []).append(f)
            return f

        return d

    def command(self, n):
        def d(f):
            self.commands[n] = f
            return f

        return d


def _client():
    c = MagicMock()
    c.chat_postMessage = AsyncMock(return_value={"ts": "111"})
    c.chat_update = AsyncMock()
    c.chat_delete = AsyncMock()
    c.files_upload_v2 = AsyncMock()
    return c


def _decision():
    return bot.permissions.Decision(allowed=True, reason="ok", role="user")


@pytest.fixture
def make_bot(monkeypatch):
    monkeypatch.setattr(bot, "AsyncApp", FakeApp)
    monkeypatch.setattr(bot.audit_log, "write", AsyncMock())
    # the routing tests below are about what happens once a message is admitted
    monkeypatch.setattr(bot, "CHANNEL_IDS", {"C"})
    monkeypatch.setattr(bot, "admitted", lambda *_args: True)

    def _make():
        return bot.PartyBot()

    return _make


class TestAdmission:
    """Closed by default: an empty list admits nobody, never everybody."""

    def test_nothing_is_admitted_without_lists(self, monkeypatch):
        monkeypatch.setattr(bot, "CHANNEL_IDS", set())
        monkeypatch.setattr(bot, "ALLOWED_USERS", set())
        assert not bot.admitted("C1", "U1")
        assert not bot.admitted("C1")

    def test_a_person_needs_both_lists_and_a_bot_message_its_channel(self, monkeypatch):
        monkeypatch.setattr(bot, "CHANNEL_IDS", {"C1"})
        monkeypatch.setattr(bot, "ALLOWED_USERS", {"U1"})
        assert bot.admitted("C1", "U1")
        assert not bot.admitted("C1", "U2")
        assert not bot.admitted("C2", "U1")
        assert bot.admitted("C1") and not bot.admitted("C2")

    async def test_a_query_that_is_not_admitted_is_dropped_and_audited(self, monkeypatch):
        monkeypatch.setattr(bot, "AsyncApp", FakeApp)
        write = AsyncMock()
        monkeypatch.setattr(bot.audit_log, "write", write)
        monkeypatch.setattr(bot, "CHANNEL_IDS", {"C1"})
        monkeypatch.setattr(bot, "ALLOWED_USERS", {"U1"})
        b = bot.PartyBot()
        client = _client()
        await b.handle_query(client=client, channel_id="C1", user_id="U9", content="hola")
        write.assert_awaited_once_with("not_admitted", user_id="U9", channel_id="C1")
        client.chat_postMessage.assert_not_awaited()

    async def test_a_forced_persona_from_an_unlisted_channel_is_ignored(self, monkeypatch):
        monkeypatch.setattr(bot, "AsyncApp", FakeApp)
        monkeypatch.setattr(bot, "CHANNEL_IDS", {"C1"})
        monkeypatch.setattr(bot, "_known_personas", lambda: {"kai": "Kai"})
        b = bot.PartyBot()
        b._handle_forced_persona = AsyncMock()
        handler = b._app.events["message"][0]
        event = {"subtype": "bot_message", "channel": "C2", "attachments": [{"title": "PAK→Kai"}]}
        await handler({"event": event}, AsyncMock(), _client())
        b._handle_forced_persona.assert_not_awaited()

    async def test_a_message_from_an_unlisted_channel_never_reaches_a_query(self, monkeypatch):
        monkeypatch.setattr(bot, "AsyncApp", FakeApp)
        monkeypatch.setattr(bot, "CHANNEL_IDS", {"C1"})
        b = bot.PartyBot()
        b.handle_query = AsyncMock()
        handler = b._app.events["message"][0]
        await handler(
            {"event": {"channel": "C2", "user": "U1", "text": "hola"}}, AsyncMock(), _client()
        )
        b.handle_query.assert_not_awaited()


# ── Module-level helpers ──────────────────────────────────────────────────────
class TestModuleHelpers:
    def test_blocks(self):
        assert bot._blocks("hello")[0]["text"]["text"] == "hello"

    def test_resolve_claude_bin_env(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_BIN", "/my/claude")
        assert bot._resolve_claude_bin() == "/my/claude"

    def test_resolve_claude_bin_which(self, monkeypatch):
        import shutil

        monkeypatch.delenv("CLAUDE_BIN", raising=False)
        monkeypatch.setattr(shutil, "which", lambda x: "/found/claude")
        assert bot._resolve_claude_bin() == "/found/claude"

    def test_load_env_plain(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bot, "_DIR", tmp_path)
        bot._load_env()

    def test_load_env_sops(self, monkeypatch, tmp_path):
        (tmp_path / ".env.sops.yaml").write_text("x")
        monkeypatch.setattr(bot, "_DIR", tmp_path)
        monkeypatch.setattr(
            bot.subprocess,
            "run",
            lambda *a, **k: MagicMock(returncode=0, stdout="FOO_BOT=bar\n# c\n"),
        )
        bot._load_env()
        assert os.environ.get("FOO_BOT") == "bar"

    def test_known_personas(self, monkeypatch, tmp_path):
        manifest = tmp_path / "agent-manifest.csv"
        manifest.write_text('name,displayName\n"kai","Kai"\n"raven","Raven"\n')
        monkeypatch.setattr(bot, "_MANIFEST_PATH", manifest)
        personas = bot._known_personas()
        assert personas == {"kai": "Kai", "raven": "Raven"}

    def test_known_personas_missing_manifest(self, monkeypatch, tmp_path):
        monkeypatch.setattr(bot, "_MANIFEST_PATH", tmp_path / "nope.csv")
        assert bot._known_personas() == {}


class TestPostHelpers:
    async def test_post(self):
        c = _client()
        assert (await bot._post(c, "C", "text"))["ts"] == "111"

    async def test_post_thread(self):
        await bot._post(_client(), "C", "text", thread_ts="t")

    async def test_update(self):
        await bot._update(_client(), "C", "ts", "text")

    async def test_update_error(self):
        c = _client()
        c.chat_update = AsyncMock(side_effect=bot.SlackApiError("e", {}))
        await bot._update(c, "C", "ts", "text")

    async def test_delete(self):
        await bot._delete(_client(), "C", "ts")

    async def test_delete_error(self):
        c = _client()
        c.chat_delete = AsyncMock(side_effect=bot.SlackApiError("e", {}))
        await bot._delete(c, "C", "ts")


class TestBotHelpers:
    async def test_att_text(self, make_bot):
        b = make_bot()
        assert b._att_text({"attachments": [{"text": "hi"}]}) == "hi"
        assert b._att_text({"text": "plain"}) == "plain"

    async def test_match_forced_persona(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot, "_known_personas", lambda: {"kai": "Kai"})
        assert await b._match_forced_persona({"attachments": [{"title": "PAK→Kai [x]"}]}) == "Kai"
        assert await b._match_forced_persona({"attachments": []}) is None
        assert await b._match_forced_persona({"attachments": [{"title": "PAK→Nobody"}]}) is None


class TestRouting:
    async def _msg_handler(self, b):
        return b._app.events["message"][0]

    async def test_routes_forced_persona(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot, "_known_personas", lambda: {"kai": "Kai"})
        b._handle_forced_persona = AsyncMock()
        h = await self._msg_handler(b)
        await h(
            {
                "event": {
                    "subtype": "bot_message",
                    "attachments": [{"title": "PAK→Kai", "text": "q"}],
                }
            },
            AsyncMock(),
            _client(),
        )
        b._handle_forced_persona.assert_awaited_with(
            {
                "subtype": "bot_message",
                "attachments": [{"title": "PAK→Kai", "text": "q"}],
            },
            _client.__self__ if False else b._handle_forced_persona.call_args.args[1],
            "Kai",
        )

    async def test_routes_unmatched_bot_message(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot, "_known_personas", lambda: {"kai": "Kai"})
        b._handle_forced_persona = AsyncMock()
        h = await self._msg_handler(b)
        await h(
            {"event": {"subtype": "bot_message", "attachments": [{"title": "just a note"}]}},
            AsyncMock(),
            _client(),
        )
        b._handle_forced_persona.assert_not_awaited()

    async def test_routes_user_query(self, make_bot):
        b = make_bot()
        b.handle_query = AsyncMock()
        h = await self._msg_handler(b)
        await h(
            {"event": {"channel": "C", "user": "U", "text": "hola mundo", "ts": "1"}},
            AsyncMock(),
            _client(),
        )
        b.handle_query.assert_awaited()

    async def test_app_mention_delegates(self, make_bot):
        b = make_bot()
        b.handle_query = AsyncMock()
        await b._app.events["app_mention"][0](
            {"event": {"channel": "C", "user": "U", "text": "hi", "ts": "1"}},
            AsyncMock(),
            _client(),
        )
        b.handle_query.assert_awaited()

    async def test_cancel_action(self, make_bot):
        b = make_bot()
        proc = MagicMock(returncode=None)
        b.active_procs["U"] = proc
        await b._app.actions["cancel_query"](AsyncMock(), {"actions": [{"value": "U"}]})
        proc.terminate.assert_called()


class TestMainEntry:
    def test_resolve_claude_bin_nvm(self, monkeypatch, tmp_path):
        import shutil

        monkeypatch.delenv("CLAUDE_BIN", raising=False)
        monkeypatch.setattr(shutil, "which", lambda x: None)
        monkeypatch.setenv("HOME", str(tmp_path))
        nvm = tmp_path / ".nvm" / "versions" / "node" / "v20" / "bin"
        nvm.mkdir(parents=True)
        (nvm / "claude").write_text("")
        assert bot._resolve_claude_bin().endswith("claude")

    async def test_main(self, monkeypatch):
        monkeypatch.setattr(bot, "AsyncApp", FakeApp)
        monkeypatch.setattr(bot.PartyBot, "startup", AsyncMock())
        handler = MagicMock()
        handler.start_async = AsyncMock()
        handler.close_async = AsyncMock()
        monkeypatch.setattr(bot, "AsyncSocketModeHandler", lambda app, tok: handler)
        await bot.main()
        handler.start_async.assert_awaited()


class TestForcedPersonaHandler:
    @pytest.fixture(autouse=True)
    def _no_worker(self, monkeypatch):
        monkeypatch.setattr(bot.PartyBot, "_thread_worker", AsyncMock())

    async def test_handle_forced_persona(self, make_bot):
        b = make_bot()
        c = _client()
        await b._handle_forced_persona(
            {"channel": "C", "ts": "1", "attachments": [{"text": "q correlation_id: `cid1`"}]},
            c,
            "Kai",
        )
        c.chat_postMessage.assert_awaited()

    async def test_handle_forced_persona_no_attachment(self, make_bot):
        b = make_bot()
        await b._handle_forced_persona(
            {"channel": "C", "ts": "1", "attachments": []}, _client(), "Kai"
        )


class TestHandleQuery:
    @pytest.fixture(autouse=True)
    def _no_worker(self, monkeypatch):
        monkeypatch.setattr(bot.PartyBot, "_thread_worker", AsyncMock())

    async def test_denied(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(
            bot.permissions, "check", lambda *a, **k: MagicMock(allowed=False, reason="blocked")
        )
        c = _client()
        await b.handle_query(client=c, channel_id="C", user_id="U", content="hi")
        c.chat_postMessage.assert_awaited()

    async def test_quiet_hours(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.permissions, "check", lambda *a, **k: _decision())
        monkeypatch.setattr(bot.permissions, "is_quiet_hours", lambda u: True)
        monkeypatch.setattr(
            bot.permissions, "_load", lambda: {"quiet_hours": {"start": "22:00", "end": "06:00"}}
        )
        c = _client()
        await b.handle_query(client=c, channel_id="C", user_id="U", content="hi")
        c.chat_postMessage.assert_awaited()

    async def test_rate_limited(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.permissions, "check", lambda *a, **k: _decision())
        monkeypatch.setattr(bot.permissions, "is_quiet_hours", lambda u: False)
        monkeypatch.setattr(bot.rate_limiter, "try_acquire", AsyncMock(return_value=False))
        c = _client()
        await b.handle_query(client=c, channel_id="C", user_id="U", content="hi")
        c.chat_postMessage.assert_awaited()

    async def test_content_blocked(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.permissions, "check", lambda *a, **k: _decision())
        monkeypatch.setattr(bot.permissions, "is_quiet_hours", lambda u: False)
        monkeypatch.setattr(bot.rate_limiter, "try_acquire", AsyncMock(return_value=True))
        monkeypatch.setattr(
            bot.content_filter, "scan", lambda c: MagicMock(verdict=bot.Verdict.BLOCK, rule_id="R1")
        )
        c = _client()
        await b.handle_query(client=c, channel_id="C", user_id="U", content="bad")
        c.chat_postMessage.assert_awaited()

    async def test_success_enqueues(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.permissions, "check", lambda *a, **k: _decision())
        monkeypatch.setattr(bot.permissions, "is_quiet_hours", lambda u: False)
        monkeypatch.setattr(bot.rate_limiter, "try_acquire", AsyncMock(return_value=True))
        monkeypatch.setattr(
            bot.content_filter, "scan", lambda c: MagicMock(verdict=bot.Verdict.ALLOW, rule_id=None)
        )
        monkeypatch.setattr(bot.anomaly_detector, "check", AsyncMock(return_value=False))
        monkeypatch.setattr(bot.interactive, "attach_cancel_button", AsyncMock())
        c = _client()
        await b.handle_query(client=c, channel_id="C", user_id="U", content="hello")
        c.chat_postMessage.assert_awaited()


class TestProcessAndStream:
    def _fake_proc(self):
        proc = MagicMock(pid=123, returncode=0)
        proc.stdin = MagicMock()
        proc.stdin.drain = AsyncMock()
        proc.stderr.read = AsyncMock(return_value=b"")
        proc.wait = AsyncMock()
        return proc

    def _item(self, c, **kw):
        base = {
            "channel_id": "C",
            "client": c,
            "processing_ts": "ts",
            "user_message": "hello",
            "decision": _decision(),
            "locale": "es",
            "user_id": "U",
            "thread_id": "C",
            "request_id": "rid",
        }
        base.update(kw)
        return base

    def _patch_session(self, monkeypatch, uuid: str | None = "uuid", count=1):
        monkeypatch.setattr(bot.session_manager, "get_or_create", AsyncMock(return_value="sess"))
        monkeypatch.setattr(bot.session_manager, "get_claude_uuid", AsyncMock(return_value=uuid))
        monkeypatch.setattr(bot.session_manager, "get_msg_count", AsyncMock(return_value=count))

    async def test_process_cache_hit(self, make_bot, monkeypatch):
        b = make_bot()
        self._patch_session(monkeypatch, uuid=None, count=0)
        monkeypatch.setattr(bot.response_cache, "get", AsyncMock(return_value="cached response"))
        c = _client()
        await b._process(self._item(c))
        c.chat_update.assert_awaited()

    async def test_process_success(self, make_bot, monkeypatch):
        b = make_bot()
        self._patch_session(monkeypatch)
        monkeypatch.setattr(bot.response_cache, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(bot.response_cache, "set", AsyncMock())
        monkeypatch.setattr(bot, "build_prompt", lambda *a, **k: ("sysprompt", "input"))
        monkeypatch.setattr(bot, "_spawn", AsyncMock(return_value=self._fake_proc()))
        monkeypatch.setattr(
            bot.PartyBot, "_stream_response", AsyncMock(return_value="result text here")
        )
        c = _client()
        await b._process(self._item(c))
        c.chat_update.assert_awaited()

    async def test_process_empty_output(self, make_bot, monkeypatch):
        b = make_bot()
        self._patch_session(monkeypatch)
        monkeypatch.setattr(bot.response_cache, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(bot, "build_prompt", lambda *a, **k: ("sys", "input"))
        monkeypatch.setattr(bot, "_spawn", AsyncMock(return_value=self._fake_proc()))
        monkeypatch.setattr(bot.PartyBot, "_stream_response", AsyncMock(return_value="  "))
        c = _client()
        await b._process(self._item(c))
        c.chat_update.assert_awaited()

    def _setup_miss(self, monkeypatch, result):
        monkeypatch.setattr(bot.response_cache, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(bot.response_cache, "set", AsyncMock())
        monkeypatch.setattr(bot, "build_prompt", lambda *a, **k: ("sys", "input"))
        monkeypatch.setattr(bot, "_spawn", AsyncMock(return_value=self._fake_proc()))
        monkeypatch.setattr(bot.PartyBot, "_stream_response", AsyncMock(return_value=result))
        monkeypatch.setattr(bot, "_slack_notify", MagicMock())

    async def test_process_tts(self, make_bot, monkeypatch):
        b = make_bot()
        self._patch_session(monkeypatch)
        self._setup_miss(monkeypatch, "result text")
        monkeypatch.setattr(bot, "tts_available", lambda: True)
        monkeypatch.setattr(bot, "tts_speak", AsyncMock(return_value="/tmp/nonexistent-x.wav"))
        c = _client()
        await b._process(self._item(c, user_message="tts: hablame"))
        c.files_upload_v2.assert_awaited()

    async def test_process_forced_persona_writes_result_and_notifies(
        self, make_bot, monkeypatch, tmp_path
    ):
        b = make_bot()
        self._patch_session(monkeypatch)
        self._setup_miss(monkeypatch, "\n".join("x" * 100 for _ in range(40)))
        monkeypatch.setattr(bot, "REPO_ROOT", str(tmp_path))
        (tmp_path / "temp").mkdir()
        await b._process(self._item(_client(), force_agent="Kai", forced_cid="cid1"))
        assert (tmp_path / "temp" / "forced-kai-cid1.txt").exists()

    async def test_process_spawn_retry(self, make_bot, monkeypatch):
        b = make_bot()
        self._patch_session(monkeypatch)
        monkeypatch.setattr(bot.response_cache, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(bot.response_cache, "set", AsyncMock())
        monkeypatch.setattr(bot, "build_prompt", lambda *a, **k: ("sys", "input"))
        monkeypatch.setattr(
            bot, "_spawn", AsyncMock(side_effect=[FileNotFoundError, self._fake_proc()])
        )
        monkeypatch.setattr(bot.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(bot, "_resolve_claude_bin", lambda: sys.executable)
        monkeypatch.setattr(bot.PartyBot, "_stream_response", AsyncMock(return_value="ok"))
        await b._process(self._item(_client()))

    async def test_process_timeout(self, make_bot, monkeypatch):
        b = make_bot()
        self._patch_session(monkeypatch)
        monkeypatch.setattr(bot.response_cache, "get", AsyncMock(return_value=None))
        monkeypatch.setattr(bot, "build_prompt", lambda *a, **k: ("sys", "input"))
        proc = self._fake_proc()
        proc.returncode = None
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        monkeypatch.setattr(bot, "_spawn", AsyncMock(return_value=proc))
        monkeypatch.setattr(bot.asyncio, "wait_for", AsyncMock(side_effect=asyncio.TimeoutError))
        monkeypatch.setattr(bot.asyncio, "sleep", AsyncMock())
        c = _client()
        await b._process(self._item(c))
        c.chat_update.assert_awaited()

    async def test_stream_response(self, make_bot):
        b = make_bot()

        async def stdout():
            for line in [
                b'{"type":"assistant","message":{"content":[{"type":"text","text":"hello"}]}}\n',
                b"\n",
                b"badjson\n",
                b'{"type":"result","total_cost_usd":0.5}\n',
            ]:
                yield line

        proc = MagicMock()
        proc.stdout = stdout()
        proc.wait = AsyncMock()
        assert await b._stream_response(proc, _client(), "C", "ts") == "hello"


class TestThreadWorkerAndStartup:
    async def test_thread_worker_processes(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.PartyBot, "_process", AsyncMock())
        q = asyncio.Queue()
        await q.put(
            {
                "enqueued_at": bot.time.monotonic(),
                "client": _client(),
                "channel_id": "C",
                "processing_ts": "ts",
                "locale": "es",
            }
        )
        await b._thread_worker("tid", q)

    async def test_thread_worker_expired(self, make_bot):
        b = make_bot()
        q = asyncio.Queue()
        await q.put(
            {
                "enqueued_at": 0.0,
                "client": _client(),
                "channel_id": "C",
                "processing_ts": "ts",
                "locale": "es",
            }
        )
        await b._thread_worker("tid", q)

    async def test_startup(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.metrics, "start_exporter", lambda p: None)
        monkeypatch.setattr(bot.health_endpoint, "start", lambda p: None)
        monkeypatch.setattr(bot.health_endpoint, "set_ready", lambda r: None)
        monkeypatch.setattr(bot.PartyBot, "_prewarm_pool", AsyncMock())
        monkeypatch.setattr(bot.PartyBot, "_cleanup_loop", AsyncMock())
        await b.startup()

    async def test_prewarm_pool(self, make_bot, monkeypatch):
        b = make_bot()
        monkeypatch.setattr(bot.asyncio, "sleep", AsyncMock())
        monkeypatch.setattr(bot.subprocess_pool, "init_pool", AsyncMock())
        await b._prewarm_pool()
