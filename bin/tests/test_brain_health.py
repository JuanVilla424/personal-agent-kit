"""bin/brain-health.sh — it parses, runs, reports per layer, and reads the backup state."""

import os
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "bin" / "brain-health.sh"


def _run(home: Path, timeout: int = 90) -> subprocess.CompletedProcess:
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, timeout=timeout, env=env, check=False
    )


def test_the_script_parses():
    assert (
        subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, check=False).returncode
        == 0
    )


def test_on_a_bare_host_it_reports_per_layer(tmp_path):
    proc = _run(tmp_path)
    out = proc.stdout
    assert "🧠 Brain health:" in out
    assert "Qdrant" in out and "memory_service" in out
    assert "no brain backups yet" in out
    assert "Brain healthy" in out or "critical layer(s) degraded" in out
    assert 0 <= proc.returncode <= 8


def test_the_backup_freshness_line_follows_the_state(tmp_path):
    brain = tmp_path / ".pak" / "backups" / "brain"
    (brain / "agent_memory").mkdir(parents=True)
    snapshot = brain / "agent_memory" / "1700000000-abcd1234ef56.snapshot"
    snapshot.write_bytes(b"snapshot")
    (brain / "latest.agent_memory.generation").write_text(snapshot.name + "\n")
    fresh = _run(tmp_path)
    assert "brain backups fresh" in fresh.stdout

    old = time.time() - 9 * 86400
    os.utime(snapshot, (old, old))
    stale = _run(tmp_path)
    assert "brain backups STALE" in stale.stdout
