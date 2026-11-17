"""bin/brain-health.sh — it parses, runs, reports per layer, and reads the backup state."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

import memory_service_stub as stub

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "bin" / "brain-health.sh"
# A systemctl with no active unit that lists FAKE_UNITS the way the real one does: every unit
# when asked for none, and only the exact names it is asked for.
FAKE_SYSTEMCTL = """#!/bin/bash
[ "$1" = "is-active" ] && exit 3
[ "$1" = "list-unit-files" ] || exit 0
shift
asked=""
for arg in "$@"; do
    case "$arg" in -*) ;; *) asked="$asked $arg" ;; esac
done
for unit in $FAKE_UNITS; do
    if [ -z "$asked" ]; then
        echo "$unit enabled enabled"
    else
        for name in $asked; do [ "$name" = "$unit" ] && echo "$unit enabled enabled"; done
    fi
done
exit 0
"""


def _run(
    home: Path, timeout: int = 90, script: Path = SCRIPT, **env: str
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=dict(os.environ, HOME=str(home), **env),
        check=False,
    )


def _kit(checkout: Path, env: str) -> Path:
    """A scratch checkout holding the script and a root .env of its own; returns the script."""
    (checkout / "bin").mkdir(parents=True)
    shutil.copy(SCRIPT, checkout / "bin" / "brain-health.sh")
    (checkout / ".env").write_text(env, encoding="utf-8")
    return checkout / "bin" / "brain-health.sh"


def _line(out: str, about: str) -> str:
    return next(line for line in out.splitlines() if about in line)


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


@pytest.mark.parametrize(
    ("service", "healthy", "says"),
    [
        ({}, True, "accepts this kit's token (3 shared / 3 personal memories)"),
        ({"token": "tok_of_another_kit"}, False, "REFUSES this kit's token"),
        ({"whoami": False}, False, "cannot confirm this kit's token (HTTP 404)"),
    ],
)
def test_a_service_counts_only_when_it_accepts_this_kits_token(tmp_path, service, healthy, says):
    """Something answering on the kit's address is not the kit's brain: with two kits on one
    machine it is the other one's, and its memories would be reported as this kit's."""
    with stub.running(**service) as port:
        script = _kit(
            tmp_path / "kit",
            f"QDRANT_PORT=9\nMEMORY_SERVICE_URL=http://127.0.0.1:{port}\n"
            'MEMORY_SERVICE_TOKEN="tok_mine"\n',
        )
        out = _run(tmp_path, script=script).stdout
    line = _line(out, "memory_service")
    assert says in line
    assert ("✔" in line) is healthy and ("✘" in line) is not healthy


@pytest.mark.parametrize(
    ("units", "says"),
    [
        ("other-agent-memory.service", "unit agent-memory.service not installed"),
        ("agent-memory.service", "unit agent-memory.service INSTALLED but INACTIVE"),
    ],
)
def test_only_the_kits_own_unit_counts_as_installed(tmp_path, units, says):
    """A unit of another kit whose name contains this one's is not this kit's unit."""
    fake = tmp_path / "fake-bin"
    fake.mkdir()
    (fake / "systemctl").write_text(FAKE_SYSTEMCTL, encoding="utf-8")
    (fake / "systemctl").chmod(0o755)
    out = _run(tmp_path, PATH=f"{fake}:{os.environ['PATH']}", FAKE_UNITS=units).stdout
    assert says in out
