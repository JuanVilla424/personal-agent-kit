#!/usr/bin/env python3
"""Claude Code TTS hook entry point.

Registered on the ``Stop`` and ``Notification`` hook events (see
``local/hooks/install-hooks.py``). Reads the hook payload from stdin, extracts the
text to speak, strips Markdown down to natural spoken language, then hands
synthesis and playback off to a detached background worker
(``tts_speak_worker.py``) so this process can return to Claude Code immediately.
Never raises and always exits 0 — a broken TTS pipeline must never break or block
a Claude Code session.

Text is never truncated — the full response is read, faster if long (see
``EdgeTTSEngine``'s speech rate) rather than cut off with a "continues" marker.

Uses only the standard library so it can run under the system ``python3`` from its
own shebang; the worker it spawns runs under the project's ``.venv`` instead, since
that is where ``edge-tts``/``python-dotenv`` are installed.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
LOG_DIR = REPO_ROOT / "temp" / "logs" / "hooks"
LOG_FILE = LOG_DIR / "tts_hook.log"
WORKER = HERE / "tts_speak_worker.py"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python3"

sys.path.insert(0, str(HERE))
from text_cleaning import clean_for_speech  # noqa: E402


def _setup_logging() -> None:
    """Configure file-only logging so stdout stays clean for the hook protocol."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(LOG_FILE),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _last_assistant_text(transcript_path: str) -> str:
    """Read a Claude Code transcript (JSONL) and return the last assistant turn's text.

    ``Stop`` events do not carry the response text directly — only the transcript
    path — so it has to be read back from disk.

    Args:
        transcript_path: Absolute path to the session transcript.

    Returns:
        The concatenated text blocks of the last assistant turn, or "" if the
        transcript is missing, empty, or has no readable assistant turn.
    """
    if not transcript_path or not os.path.isfile(transcript_path):
        return ""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        logging.exception("could not read transcript %s", transcript_path)
        return ""
    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        message = entry.get("message", {})
        if message.get("role") != "assistant":
            continue
        content = message.get("content", [])
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        text = "\n".join(part for part in parts if part)
        if text:
            return text
    return ""


def _extract_text(payload: dict) -> str:
    """Extract the text to speak from a hook payload.

    ``Notification`` events carry the text directly in ``message``. ``Stop``
    events do not — the text is read from the last assistant turn in the
    transcript file instead.

    Args:
        payload: The parsed hook JSON payload.

    Returns:
        The extracted text, or an empty string if nothing usable was found.
    """
    event = payload.get("hook_event_name", "")
    if event == "Notification":
        return payload.get("message", "") or ""
    if event == "Stop":
        return _last_assistant_text(payload.get("transcript_path", ""))
    return ""


def _speak_async(text: str, event: str) -> None:
    """Hand synthesis and playback off to a detached background worker process.

    Never blocks the caller and never raises — any failure here is logged and
    swallowed so the hook always exits 0.

    Args:
        text: The cleaned text to speak.
        event: The hook event name ("Stop" or "Notification"). Forwarded to the
            worker as part of the stdin payload — the persona rewriting layer (see
            persona_rewriter.py) uses it to decide how much liberty a rewrite may
            take: near-literal for permission/critical messages, full style for
            ordinary responses.
    """
    python = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
    try:
        # Deliberately not `with subprocess.Popen(...)`: that would wait for the
        # child on exit, defeating the whole point of a detached, non-blocking worker.
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [python, str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=str(REPO_ROOT),
        )
        assert proc.stdin is not None  # guaranteed by stdin=PIPE above
        proc.stdin.write(json.dumps({"event": event, "text": text}).encode("utf-8"))
        proc.stdin.close()
    except Exception:
        logging.exception("could not spawn tts_speak_worker")


def main() -> int:
    """Hook entry point: read stdin, extract and clean the text, spawn the worker.

    Returns:
        Always 0 — this hook must never fail or block the calling Claude Code session.
    """
    _setup_logging()
    if os.environ.get("PAK_HOOK_RUNNING"):
        # A nested `claude -p` session spawned by persona_rewriter.py — its own Stop
        # event must never re-trigger this hook (same guard judge_against_agents.py
        # uses for the same reason: stop hooks from recursing into themselves).
        return 0
    try:
        payload = json.load(sys.stdin)
        event = payload.get("hook_event_name", "")
        text = clean_for_speech(_extract_text(payload))
        if text:
            _speak_async(text, event)
        else:
            logging.info("nothing to speak for event %s", event)
    except Exception:
        logging.exception("tts_hook failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
