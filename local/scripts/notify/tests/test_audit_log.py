import asyncio
import pytest
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.asyncio
async def test_write_and_verify(tmp_path, monkeypatch):
    import security.audit_log as al

    monkeypatch.setattr(al, "_AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(al, "_prev_hash", {})

    await al.write("test_event", request_id="abc123", user_id="u1")
    await al.write("test_event_2", request_id="abc456", user_id="u2")

    import datetime

    date_str = datetime.date.today().isoformat()
    ok = al.verify_chain(date_str)
    assert ok, "Hash chain should be valid"


@pytest.mark.asyncio
async def test_tamper_detected(tmp_path, monkeypatch):
    import security.audit_log as al
    import json

    monkeypatch.setattr(al, "_AUDIT_DIR", tmp_path / "audit")
    monkeypatch.setattr(al, "_prev_hash", {})

    await al.write("event1", user_id="u1")

    import datetime

    date_str = datetime.date.today().isoformat()
    log_path = tmp_path / "audit" / f"{date_str}.jsonl"
    log_path.chmod(0o640)

    # Tamper with the file
    lines = log_path.read_text().splitlines()
    entry = json.loads(lines[0])
    entry["user_id"] = "TAMPERED"
    lines[0] = json.dumps(entry)
    log_path.write_text("\n".join(lines) + "\n")

    ok = al.verify_chain(date_str)
    assert not ok, "Tampered chain should fail verification"
