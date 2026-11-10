import os
import sys
import json
import subprocess
import threading
import urllib.parse
import urllib.request
import urllib.error
import uuid
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# Global lock — serializes outgoing posts across concurrent threads (monitor + diag)
_notify_lock = threading.Lock()

load_dotenv(Path(__file__).parent / ".env")

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

SLACK_COLORS = {
    "ok": "#2eb67d",
    "alert": "#e74c3c",
    "warn": "#f1c40f",
    "info": "#3498db",
    "pending": "#9b59b6",
}

ICONS = {
    "ok": "✅",
    "alert": "🔴",
    "warn": "⚠️",
    "info": "ℹ️",
    "pending": "⏳",
}

TASK_ICONS = {
    "pending": "🔲",
    "in_progress": "🔄",
    "completed": "✅",
    "failed": "❌",
}

TASKS_FILE = Path(__file__).parent / "tasks.json"


def _load_tasks():
    return json.loads(TASKS_FILE.read_text()) if TASKS_FILE.exists() else []


def _save_tasks(tasks):
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False))


def task_update(task_id: int, status: str, result: str = ""):
    tasks = _load_tasks()
    if status == "completed":
        tasks = [t for t in tasks if t["id"] != task_id]
    else:
        for t in tasks:
            if t["id"] == task_id:
                t["status"] = status
                if result:
                    t["result"] = result
    _save_tasks(tasks)
    send_tasks()


def _refresh_tasks():
    tasks = _load_tasks()
    env = {**os.environ, "NOTIFY_SILENT": "1"}
    for t in tasks:
        cmd = t.get("monitor_cmd")
        if not cmd:
            continue
        script = Path(__file__).parent / cmd[0]
        subprocess.run([sys.executable, str(script)] + cmd[1:], env=env)


def send_tasks():
    if os.environ.get("NOTIFY_SILENT"):
        return True
    tasks = _load_tasks()
    if not tasks:
        return False
    lines = []
    for t in tasks:
        icon = TASK_ICONS.get(t["status"], "🔲")
        line = f"{icon} **#{t['id']} — {t['title']}**"
        account = t.get("account", "")
        resource = t.get("resource", "")
        if account or resource:
            parts = []
            if account:
                parts.append(f"Account: `{account}`")
            if resource:
                parts.append(f"Resource: `{resource}`")
            line += f"\n　　↳ {' · '.join(parts)}"
        if t.get("result"):
            line += f"\n　　↳ {t['result']}"
        lines.append(line)
    has_failed = any(t["status"] == "failed" for t in tasks)
    return notify(
        "📋 Tasks — personal-agent-kit", "\n".join(lines), "alert" if has_failed else "info"
    )


def _send_webhook(url: str, payload_bytes: bytes) -> bool:
    if urllib.parse.urlparse(url).scheme not in ("https", "http"):
        print(f"ERROR: unsafe URL scheme in webhook URL", file=sys.stderr)
        return False
    req = urllib.request.Request(
        url,
        data=payload_bytes,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(  # nosec B310  # nosemgrep: bandit.B310-1
            req, timeout=10
        ) as resp:
            return resp.status in (200, 204)
    except urllib.error.HTTPError as e:
        print(f"ERROR webhook {url[:40]} {e.code}: {e.read().decode()}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return False


def _slack_payload(title: str, message: str, level: str, fields: list, now) -> bytes:
    color = SLACK_COLORS.get(level, SLACK_COLORS["info"])
    icon = ICONS.get(level, "")
    attachment = {
        "color": color,
        "title": f"{icon} {title}",
        "text": message,
        "footer": f"personal-agent-kit · {now.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "ts": int(now.timestamp()),
    }
    if fields:
        attachment["fields"] = [
            {"title": f["name"], "value": f["value"], "short": f.get("inline", True)}
            for f in fields
        ]
    return json.dumps({"attachments": [attachment]}).encode()


def notify(title: str, message: str, level: str = "info", fields: list = None) -> bool:
    if not SLACK_WEBHOOK_URL:
        print("ERROR: SLACK_WEBHOOK_URL required", file=sys.stderr)
        return False
    with _notify_lock:
        now = datetime.now().astimezone()
        return _send_webhook(
            SLACK_WEBHOOK_URL, _slack_payload(title, message, level, fields or [], now)
        )


def task_add(account: str, resource: str, title: str, result: str = ""):
    tasks = _load_tasks()
    next_id = max((t["id"] for t in tasks), default=0) + 1
    tasks.append(
        {
            "id": next_id,
            "account": account,
            "resource": resource,
            "title": title,
            "status": "pending",
            "result": result,
        }
    )
    _save_tasks(tasks)
    send_tasks()


def task_meta(task_id: int, account: str, resource: str):
    tasks = _load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t["account"] = account
            t["resource"] = resource
    _save_tasks(tasks)
    send_tasks()


def task_delete(task_id: int):
    tasks = [t for t in _load_tasks() if t["id"] != task_id]
    _save_tasks(tasks)
    send_tasks()


def task_list():
    tasks = _load_tasks()
    if not tasks:
        print("No tasks.")
        return
    for t in tasks:
        icon = TASK_ICONS.get(t["status"], "🔲")
        acc = t.get("account", "")
        res = t.get("resource", "")
        meta = f" [{acc} · {res}]" if (acc or res) else ""
        print(f"{icon} #{t['id']}{meta} — {t['title']}")
        if t.get("result"):
            print(f"   ↳ {t['result']}")


def _route(
    agent_tag: str, action_label: str, question: str, correlation_id: str | None = None
) -> bool:
    """Post a query to the channel via webhook so the bot routes it to the right agent.

    The bot detects ``agent_tag`` (e.g. 'PAK→Kai') in the embed title and bypasses normal
    user permissions. ``correlation_id`` lets the caller poll the channel and match the reply;
    a short one is generated when omitted.
    """
    cid = correlation_id or str(uuid.uuid4())[:8]
    title = f"{agent_tag} · {action_label} [{cid}]"
    body = question + f"\n\n_correlation_id: `{cid}`_"
    return notify(title, body, level="info")


def notify_agent_trigger(
    persona: str, action_label: str, question: str, correlation_id: str
) -> bool:
    """Post PAK→<persona> to Slack webhook so the bot routes it to that persona's handler.

    Works for any persona name in the current agent manifest — there is no fixed list.
    """
    return _route(f"PAK→{persona}", action_label, question, correlation_id)


def notify_agent(
    persona: str,
    action_label: str,
    question: str,
    correlation_id: str | None = None,
) -> bool:
    """Post a query to the channel via webhook so the bot routes it to `persona`.

    Works for any persona name in the current agent manifest — there is no fixed list.
    """
    return _route(f"PAK→{persona}", action_label, question, correlation_id)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) >= 2 else ""
    if cmd == "add":
        account = input("Account:        ").strip()
        resource = input("Resource:       ").strip()
        title = input("Task:           ").strip()
        result = input("Initial status: ").strip()
        task_add(account, resource, title, result)
    elif cmd == "update" and len(sys.argv) >= 4:
        result = " ".join(sys.argv[4:]) if len(sys.argv) > 4 else ""
        task_update(int(sys.argv[2]), sys.argv[3], result)
    elif cmd == "meta" and len(sys.argv) >= 5:
        task_meta(int(sys.argv[2]), sys.argv[3], sys.argv[4])
    elif cmd == "delete" and len(sys.argv) >= 3:
        task_delete(int(sys.argv[2]))
    elif cmd == "tasks":
        _refresh_tasks()
        send_tasks()
    elif cmd == "list":
        task_list()
    elif cmd == "agent" and len(sys.argv) >= 4:
        persona = sys.argv[2]
        question = " ".join(sys.argv[3:])
        ok = notify_agent(persona, "query", question)
        sys.exit(0 if ok else 1)
    elif cmd == "agent-trigger" and len(sys.argv) >= 5:
        persona = sys.argv[2]
        ok = notify_agent_trigger(persona, "query", " ".join(sys.argv[3:-1]), sys.argv[-1])
        sys.exit(0 if ok else 1)
    elif cmd == "notify" and len(sys.argv) >= 4:
        level = sys.argv[4] if len(sys.argv) > 4 else "info"
        ok = notify(sys.argv[2], sys.argv[3], level)
        sys.exit(0 if ok else 1)
    else:
        print(
            "usage: notify.py add | meta <id> <account> <resource> | update <id> <status> [result] | delete <id> | tasks | list | notify <title> <msg> [level] | agent <persona> <question> | agent-trigger <persona> <question> <cid>"
        )
        sys.exit(1)
