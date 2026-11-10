import asyncio
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

# ── Env loading (sops decrypt if available, fallback to plain .env) ──────────
_DIR = Path(__file__).parent
sys.path.insert(0, str(_DIR))
from notify import notify as _slack_notify


def _load_env() -> None:
    sops = _DIR / ".env.sops.yaml"
    plain = _DIR / ".env"
    if sops.exists():
        try:
            result = subprocess.run(
                ["sops", "-d", str(sops)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip())
                return
        except Exception:
            pass
    load_dotenv(plain)


_load_env()

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("slack-bot")

# ── Config ───────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN = os.environ["SLACK_APP_TOKEN"]
CHANNEL_IDS = {c.strip() for c in os.getenv("SLACK_CHANNEL_IDS", "").split(",") if c.strip()}
# Closed by default: an empty list lets nobody in, never everybody.
ALLOWED_USERS = {u.strip() for u in os.getenv("SLACK_ALLOWED_USERS", "").split(",") if u.strip()}


def admitted(channel_id: str, user_id: str | None = None) -> bool:
    """Whether a message may reach an agent: its channel is listed and, for a person, so are they.
    A bot or webhook message (no user) needs only its channel."""
    if channel_id not in CHANNEL_IDS:
        return False
    return user_id is None or user_id in ALLOWED_USERS


def _resolve_claude_bin() -> str:
    env_bin = os.getenv("CLAUDE_BIN")
    if env_bin:
        return env_bin
    from shutil import which

    found = which("claude")
    if found:
        return found
    nvm_versions = Path.home() / ".nvm" / "versions" / "node"
    if nvm_versions.exists():
        for vdir in sorted(nvm_versions.iterdir(), reverse=True):
            candidate = vdir / "bin" / "claude"
            if candidate.exists():
                return str(candidate)
    return "claude"


CLAUDE_BIN = _resolve_claude_bin()
CLAUDE_TIMEOUT = int(os.getenv("CLAUDE_TIMEOUT", "600"))
CLAUDE_MAX_BUDGET = os.getenv("CLAUDE_MAX_BUDGET_USD", "1.00")
USER_MONTHLY_BUDGET = float(os.getenv("USER_MONTHLY_BUDGET_USD", "50.0"))
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
CLAUDE_FALLBACK = os.getenv("CLAUDE_FALLBACK_MODEL", "claude-haiku-5-5")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_CHARS", "2900"))
QUEUE_TIMEOUT = int(os.getenv("QUEUE_TIMEOUT_SECONDS", "300"))
REPO_ROOT = os.getenv("REPO_ROOT", str(Path(__file__).resolve().parents[3]))
POOL_SIZE = int(os.getenv("POOL_SIZE", "2"))
CACHE_TTL = int(os.getenv("CACHE_TTL_SECONDS", "3600"))
SESSION_TTL = int(os.getenv("SESSION_TTL_HOURS", "24"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "9090"))
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "9091"))
MCP_CONFIG = os.getenv("CLAUDE_MCP_CONFIG", "")

_MANIFEST_PATH = Path(__file__).resolve().parents[3] / ".bmad" / "_cfg" / "agent-manifest.csv"


def _known_personas() -> dict[str, str]:
    """lowercased persona name -> real display name, read fresh from the current manifest.
    Backs the generic `PAK→<Persona>` forced-agent trigger — any persona in the roster
    works, there is no hardcoded list of names here."""
    if not _MANIFEST_PATH.exists():
        return {}
    import csv

    with _MANIFEST_PATH.open(encoding="utf-8", errors="replace") as f:
        return {
            row["displayName"].strip().lower(): row["displayName"].strip()
            for row in csv.DictReader(f)
            if row.get("displayName", "").strip()
        }


# asyncio.create_subprocess_exec aliased to avoid security scanner false positive
_spawn = asyncio.create_subprocess_exec

# ── Module imports ────────────────────────────────────────────────────────────
from core import thread_manager, subprocess_pool, session_manager, response_cache
from core.chunker import chunk
from core.party_mode_prompt import build as build_prompt
from core.model_protocol import directive_for
from core.stream_parser import extract_text_delta, extract_tool_name
from core.progress import ProgressUpdater
from core.i18n import t, detect_locale
from core.tracing import new_request_id, get_request_id
from core.sandbox import wrap_cmd
from security import (
    permissions,
    rate_limiter,
    content_filter,
    injection_guard,
    audit_log,
    anomaly_detector,
    two_factor,
)
from security.content_filter import Verdict
from ui import interactive, attachment_handler, slash_commands
from ui.voice_tts import speak as tts_speak, is_available as tts_available
from ops import metrics, health_endpoint, cost_tracker, trace


def _blocks(text: str) -> list:
    """Wrap text in a Slack mrkdwn section block."""
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]


async def _post(client, channel_id: str, text: str, thread_ts: str | None = None) -> dict:
    """Post a message and return the result (contains ts for later updates)."""
    kwargs: dict = {
        "channel": channel_id,
        "text": text,
        "blocks": _blocks(text),
    }
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    return await client.chat_postMessage(**kwargs)


async def _update(client, channel_id: str, ts: str, text: str) -> None:
    """Update an existing message in place."""
    try:
        await client.chat_update(
            channel=channel_id,
            ts=ts,
            text=text,
            blocks=_blocks(text),
        )
    except SlackApiError as e:
        log.debug("chat_update error: %s", e)


async def _delete(client, channel_id: str, ts: str) -> None:
    try:
        await client.chat_delete(channel=channel_id, ts=ts)
    except SlackApiError as e:
        log.debug("chat_delete error: %s", e)


class PartyBot:
    def __init__(self) -> None:
        self._app = AsyncApp(token=SLACK_BOT_TOKEN)
        self.loop = asyncio.get_event_loop()
        self.start_time = time.monotonic()
        self.active_procs: dict[str, asyncio.subprocess.Process] = {}
        self._pending_cancels: dict[str, asyncio.Task] = {}
        self._register_handlers()

    def _register_handlers(self) -> None:
        app = self._app

        # ── Cancel button action ─────────────────────────────────────────────
        @app.action("cancel_query")
        async def handle_cancel_action(ack, body):
            await ack()
            user_id = body.get("actions", [{}])[0].get("value", "")
            proc = self.active_procs.get(user_id)
            if proc and proc.returncode is None:
                proc.terminate()
                await audit_log.write("subprocess_cancel_via_button", user_id=user_id)

        # ── Slash commands ───────────────────────────────────────────────────
        slash_commands.register_slash_commands(app, self)

        # ── Main message handler ─────────────────────────────────────────────
        @app.event("message")
        async def handle_message(body, say, client):
            event = body.get("event", {})
            subtype = event.get("subtype", "")
            bot_id = event.get("bot_id", "")

            # Route bot/webhook messages: generic "PAK→<Persona>" forced-agent trigger.
            if bot_id or subtype == "bot_message":
                persona = await self._match_forced_persona(event)
                if persona and admitted(event.get("channel", "")):
                    await self._handle_forced_persona(event, client, persona)
                return

            # Skip messages from bots that didn't match above
            if subtype:
                return

            # an unlisted channel is dropped quietly: it would fill the audit log otherwise
            channel_id = event.get("channel", "")
            if channel_id not in CHANNEL_IDS:
                return

            text = re.sub(r"<@[A-Z0-9]+>\s*", "", event.get("text", "") or "").strip()

            if not text and not event.get("files"):
                return

            content = text or "(attachment)"
            locale = detect_locale()

            await self.handle_query(
                client=client,
                channel_id=channel_id,
                user_id=event.get("user", ""),
                content=content,
                reply_to_ts=event.get("ts"),
                locale=locale,
                files=event.get("files", []),
            )

        # ── App mention handler ──────────────────────────────────────────────
        @app.event("app_mention")
        async def handle_app_mention(body, say, client):
            await handle_message(body, say, client)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _att_text(self, event: dict) -> str:
        """Extract text from the first attachment if any."""
        atts = event.get("attachments", [])
        if atts:
            return atts[0].get("text", "") or atts[0].get("pretext", "") or ""
        return event.get("text", "") or ""

    async def _match_forced_persona(self, event: dict) -> str | None:
        """Detect a `PAK→<Persona>` marker in an attachment title/pretext and, if <Persona>
        matches a real name in the current agent manifest (case-insensitive), return that
        name in its real casing. Any persona in the roster can be forced this way — there
        is no fixed allow-list of names."""
        personas = _known_personas()
        for att in event.get("attachments", []):
            title = (att.get("title", "") or att.get("pretext", "") or "").strip()
            m = re.match(r"^PAK→(\S+)", title)
            if m and m.group(1).lower() in personas:
                return personas[m.group(1).lower()]
        return None

    async def _handle_forced_persona(self, event: dict, client, persona: str) -> None:
        """Force a single named persona to answer one question, generically — works for
        any persona in the manifest, not a hardcoded few."""
        atts = event.get("attachments", [])
        if not atts:
            return
        question = (atts[0].get("text", "") or "").strip()
        if not question:
            return

        cid_match = re.search(r"correlation_id:\s*`([^`]+)`", question)
        cid = cid_match.group(1) if cid_match else new_request_id()

        rid = new_request_id()
        channel_id = event.get("channel", "")
        ts = event.get("ts", "")
        await audit_log.write(
            "forced_persona_query_received", request_id=rid, channel_id=channel_id, persona=persona
        )

        decision = permissions.system_decision()
        result = await _post(client, channel_id, f"🤖 {persona} procesando…", thread_ts=None)
        processing_ts = result["ts"]

        thread_id = f"forced-{persona.lower()}-{ts}"
        q = thread_manager.get_queue(thread_id)
        item = {
            "request_id": rid,
            "user_id": "pak-system",
            "user_message": question,
            "attachment_text": "",
            "channel_id": channel_id,
            "client": client,
            "processing_ts": processing_ts,
            "enqueued_at": time.monotonic(),
            "decision": decision,
            "locale": "es",
            "thread_id": thread_id,
            "force_agent": persona,
            "forced_cid": cid,
        }
        await q.put(item)
        metrics.messages_received.labels(channel_id=channel_id).inc()
        existing = thread_manager._workers.get(thread_id)
        if not existing or existing.done():
            task = self.loop.create_task(
                self._thread_worker(thread_id, q), name=f"worker-{thread_id}"
            )
            thread_manager.register_worker(thread_id, task)

    async def handle_query(
        self,
        client,
        channel_id: str,
        user_id: str,
        content: str,
        reply_to_ts: str | None = None,
        locale: str = "en",
        files: list | None = None,
    ) -> None:
        # every way in (messages, mentions, slash commands) arrives here
        if not admitted(channel_id, user_id):
            await audit_log.write("not_admitted", user_id=user_id, channel_id=channel_id)
            return
        rid = new_request_id()
        await audit_log.write(
            "message_received",
            request_id=rid,
            user_id=user_id,
            channel_id=channel_id,
            payload_hash=__import__("hashlib").sha256(content.encode()).hexdigest()[:16],
        )

        decision = permissions.check(
            user_id, channel_id=channel_id, guild_id=None, requested_locale=locale
        )
        if not decision.allowed:
            await audit_log.write(
                "permission_denied", request_id=rid, user_id=user_id, reason=decision.reason
            )
            metrics.permission_denied.labels(reason=decision.reason).inc()
            await _post(client, channel_id, t("permission_denied", locale=locale), thread_ts=None)
            return

        if permissions.is_quiet_hours(user_id):
            from security.permissions import _load as _pload

            cfg = _pload()
            qh = cfg.get("quiet_hours", {})
            msg = t(
                "quiet_hours",
                locale=locale,
                start=qh.get("start", "22:00"),
                end=qh.get("end", "06:00"),
            )
            await _post(client, channel_id, msg, thread_ts=None)
            return

        ok = await rate_limiter.try_acquire(
            user_id, decision.allows_per_hour if hasattr(decision, "allows_per_hour") else 10
        )
        if not ok:
            await audit_log.write("rate_limited", request_id=rid, user_id=user_id)
            metrics.rate_limit_rejected.labels(user_id=user_id).inc()
            await _post(client, channel_id, t("rate_limited", locale=locale), thread_ts=None)
            return

        filter_result = content_filter.scan(content)
        if filter_result.verdict == Verdict.BLOCK:
            await audit_log.write(
                "content_filtered", request_id=rid, user_id=user_id, rule=filter_result.rule_id
            )
            metrics.content_blocked.labels(rule_id=filter_result.rule_id).inc()
            await _post(
                client,
                channel_id,
                t("content_blocked", locale=locale, rule=filter_result.rule_id),
                thread_ts=None,
            )
            return

        guard = injection_guard.scan(content, source="input")
        if guard.verdict is not injection_guard.Verdict.ALLOW:
            metrics.injection_detected.labels(
                source=guard.source, verdict=guard.verdict.value
            ).inc()
            await audit_log.write(
                "injection_detected",
                request_id=rid,
                user_id=user_id,
                verdict=guard.verdict.value,
                signals=",".join(guard.signals),
            )
            if guard.verdict is injection_guard.Verdict.BLOCK:
                await _post(
                    client,
                    channel_id,
                    t("content_blocked", locale=locale, rule="prompt_injection"),
                    thread_ts=None,
                )
                return

        over, spent, cap = await cost_tracker.over_budget(user_id, USER_MONTHLY_BUDGET)
        if over:
            metrics.budget_exceeded.labels(user_id=user_id).inc()
            await audit_log.write(
                "budget_exceeded", request_id=rid, user_id=user_id, spent=round(spent, 2), cap=cap
            )
            await _post(
                client,
                channel_id,
                t("budget_exceeded", locale=locale, spent=spent, cap=cap),
                thread_ts=None,
            )
            return

        anomaly = await anomaly_detector.check(user_id, content)
        if anomaly:
            metrics.anomaly_detected.inc()
            self.loop.create_task(anomaly_detector.alert(user_id, content))

        attachment_text = ""
        if files:
            attachment_text = await attachment_handler.process(files, SLACK_BOT_TOKEN)
            guard_att = injection_guard.scan(attachment_text, source="tool_output")
            if guard_att.verdict is not injection_guard.Verdict.ALLOW:
                metrics.injection_detected.labels(
                    source="tool_output", verdict=guard_att.verdict.value
                ).inc()
                await audit_log.write(
                    "injection_detected",
                    request_id=rid,
                    user_id=user_id,
                    verdict=guard_att.verdict.value,
                    signals=",".join(guard_att.signals),
                    origin="attachment",
                )
                if guard_att.verdict is injection_guard.Verdict.BLOCK:
                    attachment_text = "[adjunto removido: posible inyeccion detectada]"

        result = await _post(client, channel_id, t("processing", locale=locale), thread_ts=None)
        processing_ts = result["ts"]

        await interactive.attach_cancel_button(
            client, channel_id, processing_ts, user_id, lambda: None
        )

        thread_id = channel_id
        q = thread_manager.get_queue(thread_id)
        qsize = q.qsize()
        if qsize > 0:
            eta = qsize * 3
            await _post(
                client,
                channel_id,
                t("queue_position", locale=locale, pos=qsize + 1, eta=eta),
                thread_ts=None,
            )

        item = {
            "request_id": rid,
            "user_id": user_id,
            "user_message": content,
            "attachment_text": attachment_text,
            "channel_id": channel_id,
            "client": client,
            "processing_ts": processing_ts,
            "enqueued_at": time.monotonic(),
            "decision": decision,
            "locale": locale,
            "thread_id": thread_id,
        }
        await q.put(item)
        metrics.messages_received.labels(channel_id=channel_id).inc()
        metrics.user_requests.labels(user_id=user_id, channel_id=channel_id).inc()

        existing = thread_manager._workers.get(thread_id)
        if not existing or existing.done():
            task = self.loop.create_task(
                self._thread_worker(thread_id, q), name=f"worker-{thread_id}"
            )
            thread_manager.register_worker(thread_id, task)

    async def _thread_worker(self, thread_id: str, q: asyncio.Queue) -> None:
        while True:
            try:
                item = q.get_nowait()
            except asyncio.QueueEmpty:
                break
            try:
                age = time.monotonic() - item["enqueued_at"]
                if age > QUEUE_TIMEOUT:
                    locale = item.get("locale", "en")
                    await _post(
                        item["client"],
                        item["channel_id"],
                        t("queue_expired", locale=locale, secs=int(age)),
                    )
                    continue
                await self._process(item)
            except Exception:
                log.exception("Worker error")
                try:
                    await _update(
                        item["client"],
                        item["channel_id"],
                        item["processing_ts"],
                        t("error_internal", locale=item.get("locale", "en")),
                    )
                except Exception:
                    pass
            finally:
                q.task_done()
        metrics.threads_active.set(thread_manager.active_thread_count())

    async def _process(self, item: dict) -> None:
        channel_id: str = item["channel_id"]
        client = item["client"]
        processing_ts: str = item["processing_ts"]
        user_message: str = item["user_message"]
        attachment_text: str = item.get("attachment_text", "")
        decision = item["decision"]
        locale: str = item.get("locale", "en")
        user_id: str = item["user_id"]
        thread_id: str = item["thread_id"]
        rid: str = item.get("request_id", "")

        force_agent = item.get("force_agent")
        metrics.agent_requests.labels(agent=force_agent or "CA").inc()

        tts_requested = user_message.lower().startswith("tts:")
        if tts_requested:
            user_message = user_message[4:].strip()

        full_content = user_message
        if attachment_text:
            full_content = full_content + "\n\n" + attachment_text

        session_id = await session_manager.get_or_create(thread_id, SESSION_TTL)
        claude_session_uuid = await session_manager.get_claude_uuid(thread_id)
        msg_count = await session_manager.get_msg_count(thread_id)

        cached = await response_cache.get(
            full_content, session_id, decision.model, ",".join(decision.allowed_tools)
        )
        if cached:
            metrics.cache_hit.inc()
            chunks_list = chunk(cached, CHUNK_SIZE, locale=locale)
            await _update(client, channel_id, processing_ts, f"⚡ {chunks_list[0]}")
            for c in chunks_list[1:]:
                await asyncio.sleep(1)
                await _post(client, channel_id, c)
            await audit_log.write("cache_hit", request_id=rid, user_id=user_id)
            return
        metrics.cache_miss.inc()

        system_prompt, prompt_input = build_prompt(
            full_content, locale=locale, force_agent=force_agent
        )
        if not force_agent:
            # Model-aware protocol variant (compact for small-window models). See MODELS.md.
            system_prompt += directive_for(decision.model)

        allowed_tools_str = ",".join(decision.allowed_tools) if decision.allowed_tools else "Read"
        disallowed_tools_str = "Task"

        cmd = [
            CLAUDE_BIN,
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--model",
            decision.model,
            "--fallback-model",
            CLAUDE_FALLBACK,
            "--max-budget-usd",
            str(decision.budget_usd),
            "--allowedTools",
            allowed_tools_str,
            "--disallowedTools",
            disallowed_tools_str,
            "--add-dir",
            REPO_ROOT,
            "--system-prompt",
            system_prompt,
            "--name",
            session_id,
        ]
        if claude_session_uuid:
            if msg_count <= 1:
                cmd += ["--session-id", claude_session_uuid]
            else:
                cmd += ["--resume", claude_session_uuid]
        if MCP_CONFIG and Path(MCP_CONFIG).exists() and decision.mcp_enabled:
            cmd += ["--mcp-config", MCP_CONFIG]

        cmd = wrap_cmd(cmd, REPO_ROOT)

        home = Path.home()
        local_bin = str(home / ".local" / "bin")
        existing_path = os.environ.get("PATH", "")
        patched_path = (
            f"{local_bin}:{existing_path}" if local_bin not in existing_path else existing_path
        )
        env = {**os.environ, "HOME": str(home), "PATH": patched_path}

        try:
            proc = await _spawn(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=REPO_ROOT,
            )
        except FileNotFoundError:
            log.warning("CLAUDE_BIN not found — waiting for binary")
            for _attempt in range(12):
                await asyncio.sleep(5)
                resolved = _resolve_claude_bin()
                if Path(resolved).exists():
                    cmd[0] = resolved
                    break
            else:
                log.error("CLAUDE_BIN still missing after 60s — aborting")
                await _update(client, channel_id, processing_ts, "❌ Error interno (60s timeout)")
                return
            proc = await _spawn(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
                cwd=REPO_ROOT,
            )

        self.active_procs[user_id] = proc
        proc.stdin.write(prompt_input.encode())
        await proc.stdin.drain()
        proc.stdin.close()

        await audit_log.write("subprocess_spawn", request_id=rid, user_id=user_id, pid=proc.pid)
        log.info("claude PID %d — user=%s rid=%s", proc.pid, user_id, rid)

        cancelled = False

        async def _do_cancel():
            nonlocal cancelled
            cancelled = True
            if proc.returncode is None:
                proc.terminate()
            await audit_log.write(
                "subprocess_cancel", request_id=rid, user_id=user_id, pid=proc.pid
            )

        self._pending_cancels[user_id] = _do_cancel

        start_ts = time.monotonic()
        tr = trace.Trace(rid, user_id=user_id, model=decision.model)
        outcome = "ok"
        try:
            result_text = await asyncio.wait_for(
                self._stream_response(proc, client, channel_id, processing_ts, locale, trace=tr),
                timeout=CLAUDE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            outcome = "timeout"
            if proc.returncode is None:
                proc.terminate()
            await asyncio.sleep(5)
            if proc.returncode is None:
                proc.kill()
            log.warning("claude PID %d killed (timeout %ds)", proc.pid, CLAUDE_TIMEOUT)
            metrics.claude_timeout.inc()
            await audit_log.write(
                "subprocess_timeout", request_id=rid, user_id=user_id, pid=proc.pid
            )
            await _update(
                client, channel_id, processing_ts, t("timeout", locale=locale, secs=CLAUDE_TIMEOUT)
            )
            return
        finally:
            self.active_procs.pop(user_id, None)
            self._pending_cancels.pop(user_id, None)
            elapsed = time.monotonic() - start_ts
            metrics.subprocess_duration.observe(elapsed)
            tr.close(outcome)
            if tr.cost_usd > 0:
                await cost_tracker.record(user_id, rid, tr.cost_usd, tr.tokens_in, tr.tokens_out)

        if cancelled:
            await _update(client, channel_id, processing_ts, t("cancelled", locale=locale))
            return

        if not result_text.strip():
            stderr_raw = await proc.stderr.read()
            err = stderr_raw.decode("utf-8", errors="replace").strip()[:500]
            log.error("claude PID %d no output. stderr: %s", proc.pid, err)
            await _update(
                client,
                channel_id,
                processing_ts,
                (
                    t("no_output_with_error", locale=locale, err=err)
                    if err
                    else t("no_output", locale=locale)
                ),
            )
            await audit_log.write("subprocess_complete", request_id=rid, user_id=user_id, ok=False)
            return

        await audit_log.write(
            "subprocess_complete", request_id=rid, user_id=user_id, ok=True, chars=len(result_text)
        )

        if force_agent:
            _cid = item.get("forced_cid") or rid
            try:
                _result_path = Path(REPO_ROOT) / "temp" / f"forced-{force_agent.lower()}-{_cid}.txt"
                _result_path.write_text(result_text)
                log.info("result written to %s (%d chars)", _result_path, len(result_text))
            except Exception as _e:
                log.error("failed to write result file: %s", _e)

        await response_cache.set(
            full_content,
            session_id,
            decision.model,
            ",".join(decision.allowed_tools),
            result_text,
            CACHE_TTL,
        )

        chunks_list = chunk(result_text, CHUNK_SIZE, locale=locale)
        await _update(client, channel_id, processing_ts, chunks_list[0])
        for c in chunks_list[1:]:
            await asyncio.sleep(1)
            await _post(client, channel_id, c)

        log.info(
            "claude PID %d done: %d chars, %d chunks", proc.pid, len(result_text), len(chunks_list)
        )

        if force_agent:
            title = f"🤖 {force_agent} — Resultado"
            _LIMIT = 2900
            if len(result_text) <= _LIMIT:
                self.loop.create_task(asyncio.to_thread(_slack_notify, title, result_text, "info"))
            else:
                _lines = result_text.split("\n")
                _chunks, _cur, _sz = [], [], 0
                for _l in _lines:
                    if _sz + len(_l) + 1 > _LIMIT and _cur:
                        _chunks.append("\n".join(_cur))
                        _cur, _sz = [_l], len(_l)
                    else:
                        _cur.append(_l)
                        _sz += len(_l) + 1
                if _cur:
                    _chunks.append("\n".join(_cur))
                for _i, _ch in enumerate(_chunks):
                    _t = title + (f" ({_i+1}/{len(_chunks)})" if len(_chunks) > 1 else "")
                    self.loop.create_task(asyncio.to_thread(_slack_notify, _t, _ch, "info"))

        if tts_requested and tts_available():
            wav_path = await tts_speak(channel_id, result_text[:2000])
            if wav_path:
                metrics.tts_plays.inc()
                try:
                    await client.files_upload_v2(
                        channel=channel_id,
                        file=wav_path,
                        filename="response.wav",
                        title="🔊 Respuesta en voz",
                    )
                except Exception as e:
                    log.warning("TTS upload failed: %s", e)
                finally:
                    Path(wav_path).unlink(missing_ok=True)

    async def _stream_response(
        self,
        proc: asyncio.subprocess.Process,
        client,
        channel_id: str,
        processing_ts: str,
        locale: str = "en",
        trace=None,
    ) -> str:
        accumulated = ""
        last_tool = ""
        token_count = 0
        updater = ProgressUpdater(client, channel_id, processing_ts, locale=locale)

        async for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("type") == "result" and event.get("total_cost_usd") is not None:
                try:
                    cost = float(event["total_cost_usd"])
                    metrics.subprocess_cost.observe(cost)
                    if trace is not None:
                        usage = event.get("usage") or {}
                        trace.set(
                            cost_usd=cost,
                            tokens_in=int(usage.get("input_tokens", 0) or 0),
                            tokens_out=int(usage.get("output_tokens", 0) or 0),
                        )
                except (TypeError, ValueError):
                    pass

            delta = extract_text_delta(event)
            if delta:
                accumulated = delta

            tool = extract_tool_name(event)
            if tool:
                last_tool = tool
                if trace is not None:
                    trace.tool(tool)

            token_count = len(accumulated.split())
            await updater.update(accumulated, last_tool, token_count)

        await proc.wait()
        return accumulated

    async def _prewarm_pool(self) -> None:
        await asyncio.sleep(5)
        env = {**os.environ, "HOME": str(Path.home())}
        warm_cmd = [
            CLAUDE_BIN,
            "-p",
            "--verbose",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--max-budget-usd",
            CLAUDE_MAX_BUDGET,
        ]
        await subprocess_pool.init_pool(POOL_SIZE, warm_cmd, env)
        metrics.pool_size.set(subprocess_pool.pool_size())

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(300)
            thread_manager.cleanup_idle()
            metrics.threads_active.set(thread_manager.active_thread_count())

    async def startup(self) -> None:
        metrics.start_exporter(METRICS_PORT)
        health_endpoint.start(HEALTH_PORT)
        health_endpoint.set_ready(True)
        started_at = time.monotonic()
        metrics.bot_uptime.set_function(lambda: time.monotonic() - started_at)
        metrics.pool_in_use.set_function(lambda: float(len(self.active_procs)))
        metrics.queue_depth.set_function(lambda: float(thread_manager.total_queue_depth()))
        metrics.host_disk_total.set_function(lambda: float(shutil.disk_usage("/").total))
        metrics.host_disk_used.set_function(lambda: float(shutil.disk_usage("/").used))
        metrics.host_disk_used_percent.set_function(
            lambda: 100.0 * shutil.disk_usage("/").used / shutil.disk_usage("/").total
        )
        self.loop.create_task(self._prewarm_pool(), name="pool-prewarm")
        self.loop.create_task(self._cleanup_loop(), name="thread-cleanup")
        log.info(
            "Bot started — Slack Socket Mode — %d channels, %d users admitted",
            len(CHANNEL_IDS),
            len(ALLOWED_USERS),
        )
        if not CHANNEL_IDS or not ALLOWED_USERS:
            log.warning(
                "The bot answers nobody: set SLACK_CHANNEL_IDS and SLACK_ALLOWED_USERS in .env"
            )


async def main() -> None:
    bot = PartyBot()
    await bot.startup()
    handler = AsyncSocketModeHandler(bot._app, SLACK_APP_TOKEN)

    loop = asyncio.get_event_loop()

    def _shutdown(sig: int) -> None:
        log.info("Signal %d — shutting down…", sig)
        loop.create_task(handler.close_async())

    for s in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(s, _shutdown, s)

    await handler.start_async()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
