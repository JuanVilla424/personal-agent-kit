import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

log = logging.getLogger("permissions")

_YAML_PATH = Path(os.getenv("PERMISSIONS_FILE", Path(__file__).parent / "permissions.yaml"))
_cache: dict = {}
_cache_ts: float = 0.0
_RELOAD_INTERVAL = 30.0
_lock = threading.Lock()

_DANGEROUS = {"Bash", "Edit", "Write"}


@dataclass
class Decision:
    allowed: bool
    reason: str
    role: str
    allowed_tools: list[str] = field(default_factory=list)
    budget_usd: float = 1.00
    model: str = "claude-sonnet-5-5"
    requires_2fa: bool = False
    mcp_enabled: bool = True
    locale: str = "es"


def _load() -> dict:
    global _cache, _cache_ts
    with _lock:
        now = time.monotonic()
        if now - _cache_ts > _RELOAD_INTERVAL or not _cache:
            try:
                with _YAML_PATH.open() as f:
                    _cache = yaml.safe_load(f) or {}
                _cache_ts = now
                log.debug("Permissions reloaded from %s", _YAML_PATH)
            except Exception as e:
                log.warning("Failed to load permissions.yaml: %s", e)
                if not _cache:
                    _cache = {}
    return _cache


def _role_config(cfg: dict, role: str) -> dict:
    roles = cfg.get("roles", {})
    return roles.get(role, roles.get("user", {}))


def check(
    user_id: str,
    channel_id: str | None = None,
    guild_id: str | None = None,
    requested_locale: str = "en",
) -> Decision:
    cfg = _load()
    defaults = cfg.get("defaults", {})

    # Guild whitelist
    guild_whitelist = cfg.get("guilds", {}).get("whitelist", [])
    if guild_whitelist and guild_id and str(guild_id) not in [str(g) for g in guild_whitelist]:
        return Decision(allowed=False, reason="guild_not_whitelisted", role="none")

    # Channel whitelist
    ch_whitelist = cfg.get("channels", {}).get("whitelist", [])
    if ch_whitelist and channel_id and str(channel_id) not in [str(c) for c in ch_whitelist]:
        return Decision(allowed=False, reason="channel_not_whitelisted", role="none")

    # User role
    users = cfg.get("users", {}) or {}
    user_entry = users.get(str(user_id), {})
    role = user_entry.get("role", "user") if isinstance(user_entry, dict) else "user"

    if role == "blocked":
        return Decision(allowed=False, reason="user_blocked", role="blocked")

    role_cfg = _role_config(cfg, role)

    allowed_tools = role_cfg.get("allowed_tools", defaults.get("allowed_tools", ["Read"]))
    budget = role_cfg.get("budget_usd_per_query", defaults.get("budget_usd_per_query", 1.00))
    models = role_cfg.get("models", defaults.get("models", ["claude-sonnet-5-5"]))
    model = models[0] if models else "claude-sonnet-5-5"
    mcp_enabled = role_cfg.get("mcp_enabled", defaults.get("mcp_enabled", True))
    requires_2fa = bool(role_cfg.get("dangerous_tools_require_2fa", False))

    return Decision(
        allowed=True,
        reason="ok",
        role=role,
        allowed_tools=allowed_tools,
        budget_usd=float(budget),
        model=model,
        requires_2fa=requires_2fa,
        mcp_enabled=mcp_enabled,
        locale=requested_locale,
    )


def system_decision() -> Decision:
    cfg = _load()
    sys_role = _role_config(cfg, "system")
    models = sys_role.get("models", ["claude-sonnet-5-5"])
    return Decision(
        allowed=True,
        reason="system",
        role="system",
        allowed_tools=sys_role.get("allowed_tools", ["Read"]),
        budget_usd=float(sys_role.get("budget_usd_per_query", 2.00)),
        model=models[0] if models else "claude-sonnet-5-5",
        requires_2fa=False,
        mcp_enabled=sys_role.get("mcp_enabled", True),
    )


def needs_2fa(decision: Decision, requested_tools: list[str]) -> bool:
    if not decision.requires_2fa:
        return False
    return any(t in _DANGEROUS for t in requested_tools)


def is_quiet_hours(user_id: str) -> bool:
    cfg = _load()
    qh = cfg.get("quiet_hours", {})
    if not qh.get("enabled", False):
        return False

    users = cfg.get("users", {}) or {}
    user_entry = users.get(str(user_id), {})
    role = user_entry.get("role", "user") if isinstance(user_entry, dict) else "user"
    role_cfg = _role_config(cfg, role)
    if role_cfg.get("bypass_quiet_hours", False):
        return False

    import datetime

    try:
        tz_name = qh.get("timezone", "system")
        if tz_name and tz_name != "system":
            from zoneinfo import ZoneInfo

            now = datetime.datetime.now(ZoneInfo(tz_name)).time()
        else:
            # "system" (default) — use the host's own local time, no IANA zone
            # name to keep in sync if the box (or a copy of this repo) moves.
            now = datetime.datetime.now().time()
        start = datetime.time.fromisoformat(qh["start"])
        end = datetime.time.fromisoformat(qh["end"])
        if start <= end:
            return start <= now < end
        else:
            return now >= start or now < end
    except Exception:
        return False
