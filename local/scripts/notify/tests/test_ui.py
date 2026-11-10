"""Coverage for notify/ui/: interactive, voice_tts, attachment_handler, slash_commands."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui import attachment_handler as ah  # noqa: E402
from ui import interactive as it  # noqa: E402
from ui import slash_commands as sc  # noqa: E402
from ui import voice_tts as vt  # noqa: E402


class TestInteractive:
    async def test_attach_success(self):
        client = MagicMock()
        client.chat_update = AsyncMock()

        async def cb():
            return None

        await it.attach_cancel_button(client, "C", "ts", "U", cb)
        client.chat_update.assert_awaited()

    async def test_attach_error_swallowed(self):
        client = MagicMock()
        client.chat_update = AsyncMock(side_effect=Exception("x"))

        async def cb():
            return None

        await it.attach_cancel_button(client, "C", "ts", "U", cb)


class TestVoiceTts:
    def test_find_voice_default(self, monkeypatch, tmp_path):
        f = tmp_path / "v.onnx"
        f.write_text("x")
        monkeypatch.setattr(vt, "_DEFAULT_VOICE", str(f))
        assert vt._find_voice() == str(f)

    def test_find_voice_glob(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vt, "_DEFAULT_VOICE", "")
        monkeypatch.setattr(vt, "_VOICES_DIR", tmp_path)
        (tmp_path / "a.onnx").write_text("x")
        assert vt._find_voice().endswith("a.onnx")

    def test_find_voice_none(self, monkeypatch, tmp_path):
        monkeypatch.setattr(vt, "_DEFAULT_VOICE", "")
        monkeypatch.setattr(vt, "_VOICES_DIR", tmp_path)
        assert vt._find_voice() is None

    def test_is_available(self, monkeypatch):
        monkeypatch.setattr(vt.shutil, "which", lambda x: "/usr/bin/piper")
        monkeypatch.setattr(vt, "_find_voice", lambda: "/v.onnx")
        assert vt.is_available() is True

    async def test_speak_unavailable(self, monkeypatch):
        monkeypatch.setattr(vt, "is_available", lambda: False)
        assert await vt.speak("C", "hi") is None

    async def test_speak_success(self, monkeypatch):
        monkeypatch.setattr(vt, "is_available", lambda: True)
        monkeypatch.setattr(vt, "_find_voice", lambda: "/v.onnx")
        proc = MagicMock(returncode=0)
        proc.communicate = AsyncMock()
        monkeypatch.setattr(vt, "_spawn", AsyncMock(return_value=proc))
        assert await vt.speak("C", "hola") is not None

    async def test_speak_piper_fails(self, monkeypatch):
        monkeypatch.setattr(vt, "is_available", lambda: True)
        monkeypatch.setattr(vt, "_find_voice", lambda: "/v.onnx")
        proc = MagicMock(returncode=1)
        proc.communicate = AsyncMock()
        monkeypatch.setattr(vt, "_spawn", AsyncMock(return_value=proc))
        assert await vt.speak("C", "hola") is None

    async def test_speak_exception(self, monkeypatch):
        monkeypatch.setattr(vt, "is_available", lambda: True)
        monkeypatch.setattr(vt, "_find_voice", lambda: "/v.onnx")
        monkeypatch.setattr(vt, "_spawn", AsyncMock(side_effect=OSError("x")))
        assert await vt.speak("C", "hola") is None


class TestAttachmentHandler:
    async def test_process_too_big(self):
        out = await ah.process(
            [{"name": "big.txt", "size": ah._MAX_BYTES + 1, "url_private": "https://x"}], "tok"
        )
        assert "too large" in out

    async def test_process_no_url(self):
        out = await ah.process([{"name": "f.txt", "size": 10, "url_private": ""}], "tok")
        assert "URL not available" in out

    async def test_process_success(self, monkeypatch):
        monkeypatch.setattr(ah, "_download", AsyncMock(return_value=b"hello"))
        monkeypatch.setattr(ah, "_extract", AsyncMock(return_value="hello text"))
        out = await ah.process([{"name": "f.txt", "size": 10, "url_private": "https://x"}], "tok")
        assert "hello text" in out

    async def test_process_no_text(self, monkeypatch):
        monkeypatch.setattr(ah, "_download", AsyncMock(return_value=b""))
        monkeypatch.setattr(ah, "_extract", AsyncMock(return_value=""))
        out = await ah.process([{"name": "f.bin", "size": 10, "url_private": "https://x"}], "tok")
        assert "could not extract" in out

    async def test_process_error(self, monkeypatch):
        monkeypatch.setattr(ah, "_download", AsyncMock(side_effect=Exception("x")))
        out = await ah.process([{"name": "f.txt", "size": 10, "url_private": "https://x"}], "tok")
        assert "processing error" in out

    async def test_download_bad_scheme(self):
        with pytest.raises(ValueError):
            await ah._download("http://x", "tok")

    async def test_download_success(self, monkeypatch):
        import urllib.request

        resp = MagicMock()
        resp.read.return_value = b"data"
        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: resp)
        assert await ah._download("https://x", "tok") == b"data"

    async def test_extract_text(self):
        assert await ah._extract("f.txt", b"hello") == "hello"

    async def test_extract_pdf(self, monkeypatch):
        monkeypatch.setattr(ah, "_pdf_text", lambda data: "pdf content")
        assert await ah._extract("f.pdf", b"data") == "pdf content"

    async def test_extract_image(self, monkeypatch):
        monkeypatch.setattr(ah, "_ocr_text", lambda data, ext: "ocr text")
        assert await ah._extract("f.png", b"data") == "ocr text"

    async def test_extract_unknown(self):
        assert await ah._extract("f.xyz", b"data") == ""

    def test_pdf_text_handles_error(self):
        assert ah._pdf_text(b"notapdf") == ""

    def test_ocr_text_handles_error(self):
        assert ah._ocr_text(b"notimg", ".png") == ""


class _FakeApp:
    def __init__(self):
        self.handlers = {}
        self.client = MagicMock()

    def command(self, name):
        def deco(fn):
            self.handlers[name] = fn
            return fn

        return deco


class TestSlashCommands:
    async def test_register_and_invoke_all(self):
        app = _FakeApp()
        bot = MagicMock()
        bot.handle_query = AsyncMock()
        bot.start_time = 0.0
        bot.active_procs = {}
        sc.register_slash_commands(app, bot)
        assert "/party-ask" in app.handlers

        ack, say, respond = AsyncMock(), AsyncMock(), AsyncMock()

        await app.handlers["/party-ask"](
            ack, {"text": "hi", "channel_id": "C", "user_id": "U"}, say
        )
        bot.handle_query.assert_awaited()
        await app.handlers["/party-ask"](ack, {"text": "  "}, say)
        await app.handlers["/party-agent"](
            ack, {"text": "Kai hi", "channel_id": "C", "user_id": "U"}, say
        )
        await app.handlers["/party-agent"](ack, {"text": ""}, say)
        await app.handlers["/party-status"](ack, respond)

        proc = MagicMock(returncode=None)
        bot.active_procs = {"U": proc}
        await app.handlers["/party-cancel"](ack, respond, {"user_id": "U"})
        proc.terminate.assert_called()
        await app.handlers["/party-cancel"](ack, respond, {"user_id": "Z"})

        with patch("core.session_manager.reset", AsyncMock()):
            await app.handlers["/party-reset"](ack, respond, {"channel_id": "C"})
        with patch("ops.cost_tracker.get_user_cost", AsyncMock(return_value=(1.5, 3))):
            await app.handlers["/party-cost"](ack, respond, {"user_id": "U"})
