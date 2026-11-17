"""bin/brain_backup.py — every command against a mocked Qdrant, and the doctor's bridge."""

import fcntl
import itertools
import json
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "bin"))

import brain_backup as bb  # noqa: E402


@pytest.fixture()
def backups(tmp_path, monkeypatch):
    monkeypatch.setenv("PAK_BACKUP_ROOT", str(tmp_path / "backups"))
    monkeypatch.setattr(bb, "collections", lambda: ["c1", "c2"])
    return tmp_path / "backups"


def _fake_qdrant(monkeypatch, fail_create_coll="", fail_download=False, missing_coll=""):
    """A Qdrant stub: unique snapshot bodies per call, recorded creates/downloads/deletes."""
    counter = itertools.count(1)
    created, deleted, downloaded = [], [], []
    monkeypatch.setattr(bb, "_exists", lambda coll: coll != missing_coll)

    def create(coll):
        created.append(coll)
        return None if coll == fail_create_coll else f"snap-{coll}-{next(counter)}"

    def download(coll, name, dest):
        if fail_download:
            return False
        downloaded.append((coll, name))
        dest.write_bytes(f"body-{coll}-{name}-{next(counter)}".encode())
        return True

    def delete(coll, name):
        deleted.append((coll, name))

    monkeypatch.setattr(bb, "_create_snapshot", create)
    monkeypatch.setattr(bb, "_download_snapshot", download)
    monkeypatch.setattr(bb, "_delete_remote_snapshot", delete)
    return created, deleted, downloaded


def test_backup_stores_one_generation_per_collection(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch)
    assert bb.take() == 0
    out = capsys.readouterr().out
    assert "✔ c1:" in out and "✔ c2:" in out
    for coll in ("c1", "c2"):
        files = sorted((backups / coll).glob("*.snapshot"))
        assert len(files) == 1
        gen = backups / f"latest.{coll}.generation"
        assert gen.read_text().strip() == files[0].name


def test_backup_prunes_beyond_keep(backups, monkeypatch):
    _fake_qdrant(monkeypatch)
    for _ in range(4):
        assert bb.take(keep=2) == 0
    assert len(list((backups / "c1").glob("*.snapshot"))) == 2
    assert len(list((backups / "c2").glob("*.snapshot"))) == 2


def test_backup_reports_and_survives_a_failing_collection(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch, fail_create_coll="c2")
    assert bb.take() == 1
    assert "c2: snapshot creation failed" in capsys.readouterr().err
    assert (backups / "c1").exists() and not (backups / "c2").exists()


def test_backup_skips_a_collection_that_was_never_created(backups, monkeypatch, capsys):
    """A fresh kit has no docs collection until its docs are indexed: not a failed backup."""
    _fake_qdrant(monkeypatch, fail_create_coll="c2", missing_coll="c2")
    assert bb.take() == 0
    shown = capsys.readouterr()
    assert "– c2: not created yet" in shown.out and "failed" not in shown.err
    assert (backups / "c1").exists() and not (backups / "c2").exists()


def test_only_a_404_means_the_collection_is_not_there(monkeypatch):
    for status, there in ((404, False), (200, True), (500, True)):
        monkeypatch.setattr(bb, "_request", lambda *_a, status=status, **_k: (status, b""))
        assert bb._exists("c1") is there


def test_backup_survives_an_empty_download(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch, fail_download=True)
    assert bb.take() == 1
    assert "download came back empty" in capsys.readouterr().err


def test_backup_is_serialized_by_the_lock(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch)
    root = bb.root()
    root.mkdir(parents=True, exist_ok=True)
    handle = os.open(str(root / ".lock"), os.O_CREAT | os.O_RDWR)
    fcntl.flock(handle, fcntl.LOCK_EX)
    assert bb.take() == 0
    fcntl.flock(handle, fcntl.LOCK_UN)
    os.close(handle)
    assert "another run is in progress" in capsys.readouterr().out


def test_list_is_empty_without_backups(backups, capsys):
    assert bb.list_backups() == 1
    assert "no brain backups yet" in capsys.readouterr().out


def test_list_shows_every_generation(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch)
    bb.take()
    assert bb.list_backups() == 0
    out = capsys.readouterr().out
    assert "c1" in out and "KiB" in out and "h ago" in out


def test_restore_refuses_without_yes(backups, monkeypatch, capsys):
    uploaded = []
    monkeypatch.setattr(
        bb, "_upload_snapshot", lambda c, p: uploaded.append((c, p)) or (200, b"ok")
    )
    assert bb.restore(coll="c1", yes=False) == 2
    assert not uploaded
    assert "FULL-REPLACE" in capsys.readouterr().err


def test_restore_latest_of_every_collection(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch)
    bb.take()
    uploaded = []
    monkeypatch.setattr(
        bb, "_upload_snapshot", lambda c, p: uploaded.append((c, p)) or (200, b"ok")
    )
    assert bb.restore(yes=True) == 0
    assert {coll for coll, _ in uploaded} == {"c1", "c2"}
    assert "restored from" in capsys.readouterr().out


def test_restore_one_collection_by_id(backups, monkeypatch):
    _fake_qdrant(monkeypatch)
    bb.take()
    seen = []
    monkeypatch.setattr(bb, "_upload_snapshot", lambda c, p: seen.append(c) or (200, b"ok"))
    name = (backups / "latest.c1.generation").read_text().strip()
    assert bb.restore(target=name, coll="c1", yes=True) == 0
    assert seen == ["c1"]


def test_restore_rejects_an_unknown_collection(backups, capsys):
    assert bb.restore(coll="nope", yes=True) == 2
    assert "not one of the backed-up collections" in capsys.readouterr().err


def test_restore_reports_upload_failure(backups, monkeypatch, capsys):
    _fake_qdrant(monkeypatch)
    bb.take()
    monkeypatch.setattr(bb, "_upload_snapshot", lambda c, p: (500, b"boom"))
    assert bb.restore(yes=True) == 1
    assert "HTTP 500" in capsys.readouterr().err


def test_restore_without_a_generation_says_so(backups, capsys):
    assert bb.restore(yes=True) == 1
    assert "no generation mark yet" in capsys.readouterr().err


def test_freshness_is_none_then_fresh(backups, monkeypatch):
    _fake_qdrant(monkeypatch)
    assert bb.latest_age_hours() is None
    bb.take()
    age = bb.latest_age_hours()
    assert age is not None and age < 1
    assert bb.latest_age_hours("c2") is not None


def test_multipart_carries_the_file_and_the_field():
    path = Path(__file__)
    content_type, body = bb._multipart(path)
    assert content_type.startswith("multipart/form-data; boundary=")
    assert b'name="snapshot"' in body and path.name.encode() in body
    assert path.read_bytes() in body


def test_main_dispatches_to_the_commands(backups, monkeypatch):
    called = []
    monkeypatch.setattr(
        bb, "take", lambda keep=bb.DEFAULT_KEEP: called.append(("backup", keep)) or 0
    )
    monkeypatch.setattr(
        bb, "prune", lambda keep=bb.DEFAULT_KEEP: called.append(("prune", keep)) or 0
    )
    monkeypatch.setattr(
        bb,
        "restore",
        lambda target="latest", coll=None, yes=False: called.append(("restore", yes)) or 0,
    )
    monkeypatch.setattr(bb, "list_backups", lambda: called.append(("list",)) or 0)
    assert bb.main(["backup", "--keep", "3"]) == 0
    assert bb.main(["list"]) == 0
    assert bb.main(["prune", "--keep", "1"]) == 0
    assert bb.main(["restore", "--yes"]) == 0
    assert called == [("backup", 3), ("list",), ("prune", 1), ("restore", True)]


def test_collections_default_and_override(monkeypatch):
    monkeypatch.delenv("MEMORY_BACKUP_COLLECTIONS", raising=False)
    monkeypatch.delenv("MEMORY_COLLECTION", raising=False)
    monkeypatch.delenv("MEMORY_USER_COLLECTION", raising=False)
    monkeypatch.setattr(bb.config, "QDRANT_COLLECTION", "runbooks")
    assert bb.collections() == ["agent_memory", "agent_memory_user", "runbooks"]
    monkeypatch.setenv("MEMORY_BACKUP_COLLECTIONS", "a, b,,c")
    assert bb.collections() == ["a", "b", "c"]


def test_take_and_restore_against_a_local_qdrant_stub(tmp_path, monkeypatch, capsys):
    """The real HTTP path: take stores and deletes the remote copy; restore uploads it back."""
    monkeypatch.setenv("PAK_BACKUP_ROOT", str(tmp_path / "backups"))
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    store = {"snapshots": {}, "uploaded": b""}
    seen_auth = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, code, body=b""):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            auth = self.headers.get("api-key")
            if auth is not None:
                seen_auth.append(auth)
            if self.path.endswith("/snapshots"):
                name = f"snap-{len(store['snapshots']) + 1}"
                store["snapshots"][name] = b"snapshot-body"
                self._send(200, json.dumps({"result": {"name": name}}).encode())
            elif "/snapshots/upload" in self.path:
                length = int(self.headers.get("Content-Length", 0))
                store["uploaded"] = self.rfile.read(length)
                self._send(200, b"{}")
            else:
                self._send(404, b"{}")

        def do_GET(self):
            for name, body in store["snapshots"].items():
                if self.path.endswith(f"/snapshots/{name}"):
                    self._send(200, body)
                    return
            self._send(404, b"{}")

        def do_DELETE(self):
            for name in list(store["snapshots"]):
                if self.path.endswith(f"/snapshots/{name}"):
                    del store["snapshots"][name]
            self._send(200, b"{}")

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    monkeypatch.setenv("QDRANT_PORT", str(server.server_address[1]))
    monkeypatch.setenv("MEMORY_BACKUP_COLLECTIONS", "agent_memory")
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    try:
        assert bb.take() == 0
        assert "restored" not in capsys.readouterr().out
        assert store["snapshots"] == {}  # the remote working copy is deleted after storing
        assert bb.restore(coll="agent_memory", yes=True) == 0
        assert b"snapshot-body" in store["uploaded"]
        assert seen_auth == []  # no api key configured → no header leaks
    finally:
        server.shutdown()


def test_an_api_key_reaches_qdrant_as_a_header(tmp_path, monkeypatch):
    monkeypatch.setenv("PAK_BACKUP_ROOT", str(tmp_path / "backups"))
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            seen.append(self.headers.get("api-key"))
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    monkeypatch.setenv("QDRANT_PORT", str(server.server_address[1]))
    monkeypatch.setenv("MEMORY_BACKUP_COLLECTIONS", "agent_memory")
    monkeypatch.setenv("QDRANT_API_KEY", "sekret-value-123456")
    try:
        assert bb.take() == 1  # the 500 surfaces as a failed backup, never a silent one
        assert seen == ["sekret-value-123456"]
    finally:
        server.shutdown()


def test_the_generation_file_holds_the_filename_roundtrip(backups, monkeypatch):
    _fake_qdrant(monkeypatch)
    bb.take()
    for coll in ("c1", "c2"):
        name = json.loads(json.dumps((backups / f"latest.{coll}.generation").read_text().strip()))
        assert (backups / coll / name).exists()
        assert int(time.time()) - int(name.split("-")[0]) < 60
