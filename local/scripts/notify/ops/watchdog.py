"""
Watchdog: measures crash rate and swaps blue/green if needed.
Run by agent-bot-watchdog.service (systemd timer, every 60s).
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("watchdog")

_STATE_FILE = Path(__file__).parent.parent / "data" / "watchdog.state"
_CRASH_THRESHOLD = 3
_WINDOW_SECONDS = 300


def _load_state() -> dict:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text())
        except Exception:
            pass
    return {"crashes": [], "active_color": "blue", "last_swap": 0}


def _save_state(state: dict) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state))


def _active_color() -> str:
    for color in ("blue", "green"):
        try:
            result = subprocess.run(
                ["systemctl", "is-active", f"agent-bot-{color}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.stdout.strip() == "active":
                return color
        except Exception:
            pass
    return "blue"


def _restart_count(color: str, window: int) -> int:
    try:
        result = subprocess.run(
            [
                "journalctl",
                "-u",
                f"agent-bot-{color}",
                "--since",
                f"{window // 60} minutes ago",
                "--no-pager",
                "-q",
                "-g",
                "Started Personal Agent Kit",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.count("Started Personal Agent Kit")
    except Exception:
        return 0


def _swap(active: str, inactive: str) -> bool:
    try:
        subprocess.run(
            ["sudo", "systemctl", "start", f"agent-bot-{inactive}"], check=True, timeout=30
        )
        time.sleep(15)
        subprocess.run(["sudo", "systemctl", "stop", f"agent-bot-{active}"], check=True, timeout=30)
        log.warning("Swapped: %s → %s", active, inactive)
        return True
    except Exception as e:
        log.error("Swap failed: %s", e)
        return False


def run() -> None:
    state = _load_state()
    active = _active_color()
    inactive = "green" if active == "blue" else "blue"
    crashes = _restart_count(active, _WINDOW_SECONDS)
    log.info("Active=%s crashes_5min=%d", active, crashes)

    if crashes >= _CRASH_THRESHOLD:
        log.warning("Crash rate too high (%d in 5min) — attempting swap to %s", crashes, inactive)
        ok = _swap(active, inactive)
        if not ok:
            try:
                import sys

                sys.path.insert(0, str(Path(__file__).parent.parent))
                from notify import notify  # type: ignore

                notify(
                    level="critical",
                    title="Watchdog swap FAILED",
                    message=f"Could not swap from {active} to {inactive}. Manual intervention needed.",
                )
            except Exception:
                pass
        else:
            state["active_color"] = inactive
            state["last_swap"] = time.time()
    _save_state(state)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run()
