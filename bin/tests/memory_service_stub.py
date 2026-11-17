"""A stand-in for the kit's memory_service, for tests that need something answering on a port.

It serves /memory/health, /memory/whoami and /memory/search the way the real service does:
health answers anyone, the other two answer 200 only to the token the stand-in was started with.
"""

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def running(
    token: str = "tok_mine", whoami: bool = True, entries: int = 3, asked: list | None = None
):
    """Serve on a free loopback port and yield that port. `whoami=False` is a service without
    the route: older code, or another product listening on the same address. `asked` collects
    the paths that were requested."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # pylint: disable=invalid-name
            if asked is not None:
                asked.append(self.path)
            route = self.path.split("?")[0]
            if route == "/memory/health":
                self._send(200, {"status": "ok", "entries": entries, "user_entries": entries})
            elif route == "/memory/search" or (route == "/memory/whoami" and whoami):
                if self.headers.get("X-Memory-Token", "") == token:
                    self._send(200, {"user": "me", "admin": False, "results": []})
                else:
                    self._send(401, {"detail": "invalid memory token"})
            else:
                self._send(404, {"detail": "Not Found"})

        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):  # pylint: disable=redefined-builtin
            """Keep the test output free of access lines."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
