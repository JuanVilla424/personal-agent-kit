"""Metrics push helper for one-shot scripts.

Every run-and-exit tool (memory_index, the report generators, future scripts)
pushes its final values through this module so all agent activity lands in
Prometheus, regardless of which user or host triggered the run.

Push contract:
- PUSHGATEWAY_URL env var selects the target (default: local stack on :9391;
  point it at a different host if you run this on more than one machine of
  your own).
- Every push is grouped by host + invoked_by (+ account when applicable),
  so data from multiple hosts never collides and is always attributable in
  Grafana.
- A metrics failure must NEVER break the calling script: push() only logs.
"""

import getpass
import logging
import os
import socket
import time
import urllib.parse
import urllib.request

try:
    from prometheus_client import CollectorRegistry, Gauge, push_to_gateway

    _HAVE_PROMETHEUS_CLIENT = True
except ImportError:
    # Venvs without the lib (waf, report generators, memory_index) fall back
    # to a stdlib-only text push for push_run(); the registry API is notify-venv only.
    _HAVE_PROMETHEUS_CLIENT = False

log = logging.getLogger("metrics-push")

REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
)


def _root_env_value(key: str) -> str:
    """Read one key from the centralized root .env, stdlib-only.

    The cron triggers these tools without PUSHGATEWAY_URL exported, and not every
    venv has python-dotenv, so we parse the file by hand instead of importing it.
    Returns "" if absent. Only used for non-secret config (PUSHGATEWAY_URL).
    """
    try:
        with open(os.path.join(REPO_ROOT, ".env"), encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                if name.strip() == key:
                    return value.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


# Real env var wins (explicit override); else the centralized .env; else local default.
PUSHGATEWAY_URL = (
    os.getenv("PUSHGATEWAY_URL") or _root_env_value("PUSHGATEWAY_URL") or "http://localhost:9391"
)
PUSH_TIMEOUT_SECONDS = int(os.getenv("PUSH_TIMEOUT_SECONDS", "20"))
_push_failure_logged = False


def new_registry():
    if not _HAVE_PROMETHEUS_CLIENT:
        raise RuntimeError("prometheus_client not available — use push_run() instead")
    return CollectorRegistry()


def gauge(registry, name: str, documentation: str, labelnames=()):
    if not _HAVE_PROMETHEUS_CLIENT:
        raise RuntimeError("prometheus_client not available — use push_run() instead")
    return Gauge(name, documentation, labelnames, registry=registry)


def _grouping_path(job: str, grouping: dict) -> str:
    segments = [f"job/{urllib.parse.quote(job, safe='')}"]
    for key, value in grouping.items():
        clean = str(value).replace("/", "_") or "unknown"
        segments.append(f"{key}/{urllib.parse.quote(clean, safe='')}")
    return "/".join(segments)


def _push_text(job: str, grouping: dict, gauges: dict) -> bool:
    """stdlib-only push: PUT text exposition format to the pushgateway."""
    body = "".join(f"{name} {value}\n" for name, value in gauges.items()).encode()
    url = f"{PUSHGATEWAY_URL}/metrics/{_grouping_path(job, grouping)}"
    req = urllib.request.Request(url, data=body, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=PUSH_TIMEOUT_SECONDS) as resp:
            return 200 <= resp.status < 300
    except Exception as e:
        log.warning("metrics push (stdlib) to %s failed: %s", PUSHGATEWAY_URL, e)
        return False


def _build_grouping(account: str = "", extra_grouping: dict | None = None) -> dict:
    grouping = {
        "host": socket.gethostname(),
        "invoked_by": os.getenv("PAK_INVOKED_BY", "") or getpass.getuser(),
    }
    if account:
        grouping["account"] = account.upper()
    if extra_grouping:
        grouping.update(extra_grouping)
    return grouping


def push(job: str, registry, account: str = "", extra_grouping: dict | None = None) -> bool:
    """Push a registry to the central Pushgateway. Returns False on failure, never raises."""
    if not _HAVE_PROMETHEUS_CLIENT:
        log.warning("prometheus_client not available — registry push skipped")
        return False
    grouping = _build_grouping(account, extra_grouping)
    try:
        push_to_gateway(
            PUSHGATEWAY_URL,
            job=job,
            grouping_key=grouping,
            registry=registry,
            timeout=PUSH_TIMEOUT_SECONDS,
        )
        return True
    except Exception as e:
        global _push_failure_logged
        # Monitoring is optional: without a Pushgateway this fails on every heartbeat.
        level = logging.DEBUG if _push_failure_logged else logging.WARNING
        log.log(level, "metrics push to %s failed: %s", PUSHGATEWAY_URL, e)
        _push_failure_logged = True
        return False


def push_run(
    job: str,
    account: str = "",
    ok: bool = True,
    duration_seconds: float | None = None,
    extra_grouping: dict | None = None,
    **gauges: float,
) -> bool:
    """Convenience one-call push for script runs.

    Records <job>_last_run_timestamp_seconds, <job>_last_run_success and
    <job>_run_duration_seconds, plus any extra name=value gauges passed in.
    """
    values = {
        f"{job}_last_run_timestamp_seconds": time.time(),
        f"{job}_last_run_success": 1 if ok else 0,
    }
    if duration_seconds is not None:
        values[f"{job}_run_duration_seconds"] = duration_seconds
    values.update(gauges)

    if not _HAVE_PROMETHEUS_CLIENT:
        return _push_text(job, _build_grouping(account, extra_grouping), values)

    registry = new_registry()
    for name, value in values.items():
        gauge(registry, name, f"{job} metric {name}").set(value)
    return push(job, registry, account=account, extra_grouping=extra_grouping)
