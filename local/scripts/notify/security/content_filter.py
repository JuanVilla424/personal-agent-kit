import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml

log = logging.getLogger("content-filter")

_YAML_PATH = Path(os.getenv("PERMISSIONS_FILE", Path(__file__).parent / "permissions.yaml"))
_cache_ts: float = 0.0
_rules: list[dict] = []
_enabled: bool = True
_lock = threading.Lock()
_RELOAD_INTERVAL = 60.0


class Verdict(Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


@dataclass
class FilterResult:
    verdict: Verdict
    rule_id: str = ""
    matched: str = ""


def _reload() -> None:
    global _rules, _enabled, _cache_ts
    with _lock:
        now = time.monotonic()
        if now - _cache_ts < _RELOAD_INTERVAL:
            return
        try:
            with _YAML_PATH.open() as f:
                cfg = yaml.safe_load(f) or {}
            cf = cfg.get("content_filter", {})
            _enabled = cf.get("enabled", True)
            _rules = cf.get("rules", [])
            _cache_ts = now
        except Exception as e:
            log.warning("content_filter reload failed: %s", e)


def scan(text: str) -> FilterResult:
    _reload()
    if not _enabled:
        return FilterResult(verdict=Verdict.ALLOW)
    for rule in _rules:
        pattern = rule.get("pattern", "")
        if not pattern:
            continue
        try:
            m = re.search(pattern, text)
        except re.error:
            continue
        if m:
            return FilterResult(
                verdict=Verdict.BLOCK, rule_id=rule.get("id", "unknown"), matched=m.group(0)[:50]
            )
    return FilterResult(verdict=Verdict.ALLOW)
