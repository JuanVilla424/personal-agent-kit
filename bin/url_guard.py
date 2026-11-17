#!/usr/bin/env python3
"""url_guard.py — the web tools are a channel out, and a way back in.

What a session knows can travel inside a URL (`?q=<secret>`), and a URL can point back at this
machine (`http://127.0.0.1:7800`, the memory service) or at a cloud metadata address. This guard
sees every fetched URL and every search query, in both engines: Claude Code through
local/hooks/url-guard.py and OpenCode through .opencode/plugins/url-guard.js.

  - only http(s): no file://, ftp://, gopher://, javascript:…
  - no loopback, private, link-local or special-purpose host, no `localhost`, `*.local` or
    `*.internal`, and no public name that resolves to one (DNS rebinding)
  - no credentials in the URL (user:pass@host)
  - no secret-looking material in the path, query or fragment: `token=`, `key=`, `password=`…, a
    JWT, a known token shape, a base64 run of 40+ or a hex run of 48+ (a commit sha has 40: it
    passes, and a slug keeps its hyphens)
  - no URL over 512 characters, no query over 200

Limit: a redirect is not seen here. Stdlib only.

Usage: echo '{"tool": "webfetch", "args": {"url": "…"}}' | bin/url_guard.py
"""

import ipaddress
import json
import re
import socket
import sys
import threading
from collections.abc import Callable
from urllib.parse import unquote, urlsplit

MAX_URL = 512
MAX_QUERY = 200
DNS_TIMEOUT_S = 2.0
PREFIX = "BLOCKED (url-guard)"

_SECRET_KEY = re.compile(
    r"(?:^|[?&#/;,.])(?:api[_-]?key|access[_-]?key|secret|token|passw(?:or)?d|pwd|auth|"
    r"authorization|bearer|cookie|session(?:[_-]?id)?|sig(?:nature)?|credentials?)\s*[=:]",
    re.IGNORECASE,
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
# Known token shapes: the runs below miss a token whose prefix and separator split it, or a short one.
_SECRET_PREFIX = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"gh[pousr]_[A-Za-z0-9]{36}"
    r"|github_pat_[A-Za-z0-9_]{22,}"
    r"|glpat-[A-Za-z0-9_-]{20,}"
    r"|xox[abposr]-[A-Za-z0-9-]{10,}"
    r"|(?:AKIA|ASIA)[A-Z0-9]{16}"
    r"|AIza[A-Za-z0-9_-]{35}"
    r"|(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"
    r")"
)
# An `sk-` key only when its body mixes classes: `sk-learn-tutorial` is a slug.
_SK_KEY = re.compile(r"(?<![A-Za-z0-9])sk-(?:proj-|ant-)?([A-Za-z0-9_-]{20,})")
_BASE64_RUN = re.compile(r"[A-Za-z0-9+]{40,}={0,2}")
_HEX_RUN = re.compile(r"\b[0-9a-f]{48,}\b", re.IGNORECASE)
_PRIVATE_NAME = re.compile(r"^(?:localhost|.+\.localhost|.+\.local|.+\.internal|.+\.home|.+\.lan)$")
_UNSAFE_URL_CHARS = re.compile(r"[\s\\\x00-\x1f]")
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_SIX_TO_FOUR = ipaddress.ip_network("2002::/16")


def _looks_encoded(run: str) -> bool:
    """A base64 blob mixes upper, lower and digits; a sha or a lowercase slug does not."""
    return all(re.search(cls, run) for cls in ("[A-Z]", "[a-z]", "[0-9]"))


def _secret_like(text: str) -> str | None:
    """What in the text looks like a secret, or None."""
    decoded = unquote(text)
    if _SECRET_KEY.search(decoded):
        return "secret-like key"
    if _JWT.search(decoded):
        return "a JWT"
    if _SECRET_PREFIX.search(decoded) or any(
        _looks_encoded(m.group(1)) for m in _SK_KEY.finditer(decoded)
    ):
        return "a known token shape"
    if _HEX_RUN.search(decoded):
        return "a hex run"
    if any(_looks_encoded(run) for run in _BASE64_RUN.findall(decoded)):
        return "a base64 run"
    return None


def _ip_of(host: str):
    """The address a host literally spells, legacy forms included (`2130706433`, `0x7f.1`)."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        return ipaddress.ip_address(socket.inet_aton(host))
    except OSError:
        return None


def _private_ip(ip) -> bool:
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.version == 6 and (ip in _NAT64 or ip in _SIX_TO_FOUR):
        return True
    return not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def _private_host(host: str) -> bool:
    ip = _ip_of(host)
    return _private_ip(ip) if ip else _PRIVATE_NAME.match(host.lower()) is not None


def check_url(raw: object) -> str | None:
    """Why this URL is refused, looking only at its text, or None."""
    url = str(raw or "")
    if not url.strip():
        return None
    if len(url) > MAX_URL:
        return f"{PREFIX}: URL longer than {MAX_URL} chars"
    # A backslash splits the host differently here and in the client that fetches it.
    if _UNSAFE_URL_CHARS.search(url):
        return f"{PREFIX}: not a valid absolute URL"
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return f"{PREFIX}: not a valid absolute URL"
    if not parts.scheme:
        return f"{PREFIX}: not a valid absolute URL"
    if parts.scheme.lower() not in ("http", "https"):
        return f"{PREFIX}: scheme {parts.scheme} is not http(s)"
    if not host:
        return f"{PREFIX}: not a valid absolute URL"
    if parts.username or parts.password:
        return f"{PREFIX}: credentials inside the URL"
    if _private_host(host):
        return f"{PREFIX}: {host} is a loopback, private or local host"
    query = f"?{parts.query}" if parts.query else ""
    fragment = f"#{parts.fragment}" if parts.fragment else ""
    why = _secret_like(parts.path + query + fragment)
    return f"{PREFIX}: the URL carries {why}" if why else None


def _lookup(host: str) -> list[str]:
    """Every address the name resolves to, [] if the resolver fails or takes too long.

    A resolver error is not a verdict: the fetch would fail on it anyway. getaddrinfo has no
    timeout of its own, and a daemon thread never holds the process back.
    """
    found: list[str] = []

    def resolve() -> None:
        try:
            found.extend(str(info[4][0]) for info in socket.getaddrinfo(host, None))
        except OSError:
            pass

    thread = threading.Thread(target=resolve, daemon=True)
    thread.start()
    thread.join(DNS_TIMEOUT_S)
    return list(found)


def check_url_resolved(raw: object, lookup: Callable[[str], list[str]] = _lookup) -> str | None:
    """check_url(), plus where a public name really points."""
    lexical = check_url(raw)
    if lexical or not str(raw or "").strip():
        return lexical
    host = urlsplit(str(raw)).hostname or ""
    if _ip_of(host):
        return None
    for address in lookup(host):
        ip = _ip_of(address.split("%", 1)[0])
        if ip and _private_ip(ip):
            return f"{PREFIX}: {host} resolves to {address}, a private address"
    return None


def check_query(raw: object) -> str | None:
    """Why this search query is refused, or None."""
    query = str(raw or "")
    if not query.strip():
        return None
    if len(query) > MAX_QUERY:
        return f"{PREFIX}: search query longer than {MAX_QUERY} chars"
    why = _secret_like(query)
    return f"{PREFIX}: the search query carries {why}" if why else None


def check_tool(tool: str, args: dict, lookup: Callable[[str], list[str]] = _lookup) -> str | None:
    """The verdict for one web tool call. Any other tool is not this guard's business."""
    if tool == "webfetch":
        return check_url_resolved(args.get("url"), lookup)
    if tool == "websearch":
        return check_query(args.get("query"))
    return None


def main() -> int:
    call = json.load(sys.stdin)
    reason = check_tool(str(call.get("tool", "")), call.get("args") or {})
    print(json.dumps({"allowed": reason is None, "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
