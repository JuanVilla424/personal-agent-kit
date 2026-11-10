"""bin/egress.py: the worker container's one way out lets through only what is on its list."""

import json
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
from pathlib import Path

import pytest

EGRESS = Path(__file__).resolve().parents[2] / "bin" / "egress.py"
sys.path.insert(0, str(EGRESS.parent))

import egress  # noqa: E402


class _Echo(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        while data := self.request.recv(4096):
            self.request.sendall(data)


@pytest.fixture
def echo():
    """A TCP server on the loopback that sends back what it gets: the outside world."""
    server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Echo)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def proxy(echo):
    """The host's proxy on a unix socket, with only the echo server on its list."""
    with tempfile.TemporaryDirectory(prefix="pak-egress-test-") as folder:
        log = Path(folder) / "egress.jsonl"
        server = egress.serve_proxy(Path(folder) / "egress.sock", [echo], log)
        yield server, log
        server.shutdown()
        server.server_close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ask_at(socket_path: str, request: bytes) -> tuple[bytes, socket.socket]:
    """Send one request to the proxy's socket: its answer's head, and the open connection."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(5)
    conn.connect(socket_path)
    conn.sendall(request)
    head, _ = egress._read_head(conn)
    return head, conn


def ask(proxy_server, request: bytes) -> tuple[bytes, socket.socket]:
    return ask_at(proxy_server.server_address, request)


def logged(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    "text, spelled",
    [
        ("API.Anthropic.com:443", "api.anthropic.com:443"),
        ("[::1]:8080", "[::1]:8080"),
        ("::1:8080", "[::1]:8080"),
        (" 127.0.0.1:08080 ", "127.0.0.1:8080"),
    ],
)
def test_a_destination_has_one_spelling(text, spelled):
    assert egress.destination(text) == spelled


@pytest.mark.parametrize(
    "text", ["api.anthropic.com", ":443", "host:0", "host:65536", "host:https"]
)
def test_a_destination_without_host_and_port_is_refused(text):
    with pytest.raises(ValueError):
        egress.destination(text)


def test_the_list_is_the_model_api_the_base_url_and_what_the_human_adds():
    assert egress.allowlist({}) == ["api.anthropic.com:443"]
    env = {
        "ANTHROPIC_BASE_URL": "https://Gateway.example.com/anthropic",
        "PAK_WORKER_EGRESS": "pypi.org:443, files.pythonhosted.org:443,",
    }
    assert egress.allowlist(env) == [
        "api.anthropic.com:443",
        "gateway.example.com:443",
        "pypi.org:443",
        "files.pythonhosted.org:443",
    ]
    with pytest.raises(ValueError):
        egress.allowlist({"PAK_WORKER_EGRESS": "pypi.org"})
    with pytest.raises(ValueError):
        egress.allowlist({"ANTHROPIC_BASE_URL": "not-a-url"})


def test_only_a_base_url_on_the_loopback_needs_a_forward():
    assert egress.forwards({"ANTHROPIC_BASE_URL": "http://127.0.0.1:8123"}) == ["127.0.0.1:8123"]
    assert egress.forwards({"ANTHROPIC_BASE_URL": "http://localhost:9000/v1"}) == ["localhost:9000"]
    assert egress.forwards({"ANTHROPIC_BASE_URL": "https://gateway.example.com"}) == []
    assert egress.forwards({}) == []


def test_a_listed_destination_goes_through_both_ways(proxy, echo):
    server, log = proxy
    head, conn = ask(server, f"CONNECT {echo} HTTP/1.1\r\nHost: {echo}\r\n\r\n".encode())
    assert head.startswith(b"HTTP/1.1 200")
    conn.sendall(b"ping")
    assert conn.recv(4) == b"ping"
    conn.close()
    assert logged(log)[0] | {"at": ""} == {"at": "", "target": echo, "allowed": True}


def test_everything_else_is_refused_and_recorded(proxy):
    server, log = proxy
    refused = {
        b"CONNECT example.com:443 HTTP/1.1\r\n\r\n": b"HTTP/1.1 403",
        b"GET http://example.com/ HTTP/1.1\r\nHost: example.com\r\n\r\n": b"HTTP/1.1 405",
        b"CONNECT example.com HTTP/1.1\r\n\r\n": b"HTTP/1.1 400",
    }
    for request, status in refused.items():
        head, conn = ask(server, request)
        conn.close()
        assert head.startswith(status)
    assert [(e["target"], e["allowed"]) for e in logged(log)] == [
        ("example.com:443", False),
        ("http://example.com/", False),
        ("example.com", False),
    ]
    assert egress.summary(log) == {
        "allowed": 0,
        "denied": ["example.com", "example.com:443", "http://example.com/"],
    }


def test_a_listed_destination_that_does_not_answer_is_a_bad_gateway():
    closed = f"127.0.0.1:{free_port()}"
    with tempfile.TemporaryDirectory(prefix="pak-egress-test-") as folder:
        log = Path(folder) / "egress.jsonl"
        server = egress.serve_proxy(Path(folder) / "egress.sock", [closed], log)
        head, conn = ask(server, f"CONNECT {closed} HTTP/1.1\r\n\r\n".encode())
        conn.close()
        server.shutdown()
        server.server_close()
        assert head.startswith(b"HTTP/1.1 502")
        assert logged(log)[0]["reason"].startswith("unreachable")
        assert egress.summary(log) == {"allowed": 0, "denied": []}


def test_a_head_that_never_ends_is_not_read(proxy):
    server, log = proxy
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(5)
    conn.connect(server.server_address)
    conn.sendall(b"CONNECT " + b"a" * egress.HEAD_LIMIT)
    try:
        answer = conn.recv(64)
    except ConnectionResetError:  # hung up with bytes unread
        answer = b""
    conn.close()
    assert answer == b"" and egress.summary(log) == {"allowed": 0, "denied": []}


def test_a_silent_client_is_not_recorded(proxy):
    server, log = proxy
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(server.server_address)
    conn.close()
    assert egress.summary(log) == {"allowed": 0, "denied": []}


def test_a_forward_asks_the_proxy_for_its_destination_first(proxy, echo):
    """A forward's client speaks plain bytes: the bridge sends the CONNECT for it. (The bridge's
    own loopback is the container's, so here the forward is driven through one socket pair.)"""
    server, log = proxy
    container_side, client = socket.socketpair()
    relay = threading.Thread(
        target=egress._relay, args=(container_side, server.server_address, echo)
    )
    relay.start()
    client.settimeout(5)
    client.sendall(b"ping")
    assert client.recv(4) == b"ping"
    client.close()
    relay.join(5)
    assert egress.summary(log) == {"allowed": 1, "denied": []}


def test_the_bridge_runs_the_command_with_the_socket_as_its_only_way_out(proxy):
    """Inside the container: the command's HTTPS_PROXY is refused the world, and a forward the
    proxy does not list is hung up on. The bridge exits with the command's code."""
    server, log = proxy
    listen = f"127.0.0.1:{free_port()}"
    forward = f"127.0.0.1:{free_port()}"
    client = textwrap.dedent(f"""
        import socket, sys
        host, port = "{listen}".split(":")
        with socket.create_connection((host, int(port)), timeout=5) as c:
            c.sendall(b"CONNECT example.com:443 HTTP/1.1\\r\\n\\r\\n")
            refused = c.recv(64).startswith(b"HTTP/1.1 403")
        host, port = "{forward}".split(":")
        with socket.create_connection((host, int(port)), timeout=5) as c:
            c.sendall(b"ping")
            try:
                hung_up = c.recv(4) == b""
            except ConnectionResetError:  # closed with "ping" unread: a reset, not an EOF
                hung_up = True
        sys.exit(7 if refused and hung_up else 1)
        """)
    code = egress.bridge(server.server_address, listen, [forward], [sys.executable, "-c", client])
    assert code == 7
    assert egress.summary(log)["denied"] == [
        "127.0.0.1:" + forward.split(":")[1],
        "example.com:443",
    ]


def test_the_bridge_reports_a_command_it_cannot_run_or_a_signal(proxy):
    server, _ = proxy
    listen = f"127.0.0.1:{free_port()}"
    assert egress.bridge(server.server_address, listen, [], ["/no/such/program"]) == 127
    kill = [sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"]
    assert egress.bridge(server.server_address, f"127.0.0.1:{free_port()}", [], kill) == 143


def test_the_command_line(proxy, tmp_path):
    server, _ = proxy
    listen = f"127.0.0.1:{free_port()}"
    argv = ["bridge", "--socket", server.server_address, "--listen", listen, "--"]
    assert egress.main(argv + [sys.executable, "-c", "raise SystemExit(4)"]) == 4
    with pytest.raises(SystemExit):
        egress.main(["bridge", "--socket", server.server_address])
    with tempfile.TemporaryDirectory(prefix="pak-egress-test-") as folder:
        sock, log = Path(folder) / "egress.sock", tmp_path / "egress.jsonl"
        proc = subprocess.Popen(
            [sys.executable, str(EGRESS), "proxy", "--socket", str(sock), "--log", str(log)],
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 10
        while not sock.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        head, conn = ask_at(str(sock), b"CONNECT example.com:443 HTTP/1.1\r\n\r\n")
        conn.close()
        proc.send_signal(signal.SIGINT)
        assert proc.wait(10) == 0
    assert head.startswith(b"HTTP/1.1 403")
    assert "api.anthropic.com:443" in (proc.stderr.read() if proc.stderr else "")
