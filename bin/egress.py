#!/usr/bin/env python3
"""egress.py — the worker container's only way out: a proxy on the host, a bridge inside.

`pak task` runs its engine with `docker run --network none`: the kernel leaves the container a
loopback and nothing else. Its one door is a unix socket the host mounts into it.

  proxy   (host)       listens on that socket and accepts only `CONNECT host:port` to a
                       destination on its list: it connects there and pipes the bytes. Every
                       request, let through or refused, is one JSON line in --log.
  bridge  (container)  listens on 127.0.0.1:3128 for the engine's HTTPS_PROXY and hands each
                       connection to the socket. `--forward HOST:PORT` also listens on that
                       loopback address and sends the CONNECT itself, for a model served on the
                       host's loopback (ANTHROPIC_BASE_URL=http://127.0.0.1:PORT). Then it runs
                       the command and exits with its code.

The list: api.anthropic.com:443, the host of ANTHROPIC_BASE_URL, and the host:port entries of
PAK_WORKER_EGRESS (comma-separated).

Usage:
  bin/egress.py proxy --socket DIR/egress.sock --log egress.jsonl [--allow HOST:PORT ...]
  bin/egress.py bridge --socket /run/pak/egress.sock [--forward 127.0.0.1:8080] -- claude -p …
"""

import argparse
import json
import os
import socket
import socketserver
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

MODEL_API = "api.anthropic.com:443"
PROXY_LISTEN = "127.0.0.1:3128"
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
HEAD_LIMIT = 8192  # bytes of a request head; past it the request is not read
HEAD_TIMEOUT_S = 10
CONNECT_TIMEOUT_S = 10
CHUNK = 65536
ESTABLISHED = b"HTTP/1.1 200 Connection established\r\n\r\n"


def destination(text: str) -> str:
    """`host:port`, spelled the one way the list compares: lower-case host, IPv6 in brackets."""
    host, sep, port = text.strip().rpartition(":")
    host = host.strip("[]").lower()
    if not sep or not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise ValueError(f"not a host:port destination: {text!r}")
    return f"[{host}]:{int(port)}" if ":" in host else f"{host}:{int(port)}"


def url_destination(url: str) -> str:
    parts = urlsplit(url)
    if not parts.hostname:
        raise ValueError(f"no host in {url!r}")
    return destination(f"{parts.hostname}:{parts.port or (443 if parts.scheme == 'https' else 80)}")


def _address(dest: str) -> tuple[str, int]:
    host, _, port = dest.rpartition(":")
    return host.strip("[]"), int(port)


def allowlist(env=None) -> list[str]:
    """Where the worker may connect: the model API, the host of ANTHROPIC_BASE_URL, and the
    entries of PAK_WORKER_EGRESS."""
    env = os.environ if env is None else env
    allowed = [MODEL_API]
    if env.get("ANTHROPIC_BASE_URL", "").strip():
        allowed.append(url_destination(env["ANTHROPIC_BASE_URL"].strip()))
    allowed += [destination(e) for e in env.get("PAK_WORKER_EGRESS", "").split(",") if e.strip()]
    return list(dict.fromkeys(allowed))


def forwards(env=None) -> list[str]:
    """What the bridge must serve itself: a base URL on the host's loopback points, inside the
    container, at the container's own loopback, where nothing else listens."""
    env = os.environ if env is None else env
    base = env.get("ANTHROPIC_BASE_URL", "").strip()
    return [url_destination(base)] if base and urlsplit(base).hostname in LOOPBACK_HOSTS else []


def summary(log: Path) -> dict:
    """What a task's container asked for: connections let through, and destinations refused."""
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    entries = [json.loads(line) for line in lines if line.strip()]
    return {
        "allowed": sum(1 for e in entries if e["allowed"] and "reason" not in e),
        "denied": sorted({e["target"] for e in entries if not e["allowed"]}),
    }


def _reply(status: str) -> bytes:
    return f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode()


def _read_head(conn: socket.socket) -> tuple[bytes, bytes]:
    """The request or response head up to its blank line, and whatever came after it; an empty
    head when the other side hangs up first or sends more than HEAD_LIMIT without ending it."""
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk or len(data) + len(chunk) > HEAD_LIMIT:
            return b"", b""
        data += chunk
    head, _, rest = data.partition(b"\r\n\r\n")
    return head, rest


def _pipe(a: socket.socket, b: socket.socket) -> None:
    """Copy bytes both ways until both sides are done, then close both."""

    def copy(src: socket.socket, dst: socket.socket) -> None:
        try:
            while chunk := src.recv(CHUNK):
                dst.sendall(chunk)
        except OSError:
            pass  # a reset is one of the ways a side ends its stream
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass  # that side is already gone

    back = threading.Thread(target=copy, args=(b, a), daemon=True)
    back.start()
    copy(a, b)
    back.join()
    a.close()
    b.close()


# ── proxy (host) ─────────────────────────────────────────────────────────────────────────────────


class Proxy(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """The host side: a CONNECT to a listed destination, or nothing."""

    daemon_threads = True

    def __init__(self, socket_path: Path, allowed: list[str], log: Path) -> None:
        self.allowed = {destination(a) for a in allowed}
        self.log = log
        self.lock = threading.Lock()
        super().__init__(str(socket_path), _ProxyHandler)

    def record(self, target: str, allowed: bool, reason: str = "") -> None:
        entry = {
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "target": target,
            "allowed": allowed,
        }
        if reason:
            entry["reason"] = reason
        with self.lock, self.log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


class _ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        proxy: Proxy = self.server  # type: ignore[assignment]
        conn: socket.socket = self.request
        conn.settimeout(HEAD_TIMEOUT_S)
        try:
            head, rest = _read_head(conn)
        except OSError:
            head, rest = b"", b""
        if not head:
            return  # it hung up or stayed silent: it never named a destination to judge
        words = head.split(b"\r\n", 1)[0].decode("latin-1").split()
        if len(words) != 3 or words[0] != "CONNECT":
            proxy.record(words[1] if len(words) > 1 else "?", False, "only CONNECT goes out")
            conn.sendall(_reply("405 Method Not Allowed"))
            return
        try:
            target = destination(words[1])
        except ValueError:
            proxy.record(words[1], False, "not host:port")
            conn.sendall(_reply("400 Bad Request"))
            return
        if target not in proxy.allowed:
            proxy.record(target, False, "not on the list")
            conn.sendall(_reply("403 Forbidden"))
            return
        try:
            upstream = socket.create_connection(_address(target), timeout=CONNECT_TIMEOUT_S)
        except OSError as e:
            proxy.record(target, True, f"unreachable: {e}")
            conn.sendall(_reply("502 Bad Gateway"))
            return
        proxy.record(target, True)
        conn.settimeout(None)
        upstream.settimeout(None)
        conn.sendall(ESTABLISHED)
        if rest:
            upstream.sendall(rest)
        _pipe(conn, upstream)


def serve_proxy(socket_path: Path, allowed: list[str], log: Path) -> Proxy:
    """A proxy answering on its socket from a background thread; `shutdown()` stops it."""
    proxy = Proxy(socket_path, allowed, log)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    return proxy


# ── bridge (container) ───────────────────────────────────────────────────────────────────────────


def _relay(client: socket.socket, socket_path: str, target: str) -> None:
    """Hand one connection to the host's proxy; for a forward, ask for its destination first."""
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        upstream.connect(socket_path)
        if target:
            upstream.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
            head, rest = _read_head(upstream)
            if not head.startswith(b"HTTP/1.1 200"):
                raise OSError(f"the proxy refused {target}: {head[:60]!r}")
            if rest:
                client.sendall(rest)
    except OSError as e:
        print(f"egress bridge: no way out through {socket_path}: {e}", file=sys.stderr)
        client.close()
        upstream.close()
        return
    _pipe(client, upstream)


class _RelayHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        _relay(self.request, self.server.socket_path, self.server.target)  # type: ignore[attr-defined]


class _Listener(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class _Listener6(_Listener):
    address_family = socket.AF_INET6


def _listen(where: str, socket_path: str, target: str) -> _Listener:
    host, port = _address(destination(where))
    host = "127.0.0.1" if host == "localhost" else host
    server = (_Listener6 if ":" in host else _Listener)((host, port), _RelayHandler)
    server.socket_path = socket_path  # type: ignore[attr-defined]
    server.target = target  # type: ignore[attr-defined]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def bridge(socket_path: str, listen: str, forward: list[str], command: list[str]) -> int:
    servers = [_listen(listen, socket_path, "")]
    servers += [_listen(where, socket_path, destination(where)) for where in forward]
    try:
        code = subprocess.run(command, check=False).returncode
    except OSError as e:
        print(f"egress bridge: cannot run {command[0]}: {e}", file=sys.stderr)
        code = 127
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
    return code if code >= 0 else 128 - code


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="the worker container's only way out")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_proxy = sub.add_parser("proxy", help="the host side: serve the socket until stopped")
    p_proxy.add_argument("--socket", required=True, type=Path)
    p_proxy.add_argument("--log", required=True, type=Path)
    p_proxy.add_argument(
        "--allow", action="append", default=[], help="HOST:PORT, repeatable (default: the list)"
    )
    p_bridge = sub.add_parser("bridge", help="the container side: run a command through the socket")
    p_bridge.add_argument("--socket", required=True)
    p_bridge.add_argument("--listen", default=PROXY_LISTEN)
    p_bridge.add_argument("--forward", action="append", default=[], help="HOST:PORT, repeatable")
    p_bridge.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args(argv)

    if args.cmd == "proxy":
        proxy = Proxy(args.socket, args.allow or allowlist(), args.log)
        print(f"egress proxy on {args.socket}: {', '.join(sorted(proxy.allowed))}", file=sys.stderr)
        try:
            proxy.serve_forever()
        except KeyboardInterrupt:
            pass  # Ctrl-C is how a human stops it
        finally:
            proxy.server_close()
        return 0
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        ap.error("bridge needs a command after --")
    return bridge(args.socket, args.listen, args.forward, command)


if __name__ == "__main__":
    sys.exit(main())
