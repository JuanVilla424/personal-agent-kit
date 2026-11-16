"""local/scripts/qdrant_health_check.sh — it watches this checkout's Qdrant, by the name its
port gives it, and tells Slack when it goes down and when it is back."""

import os
import shutil
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "qdrant_health_check.sh"
# docker lists FAKE_RUNNING as running and knows no stopped container; curl logs what it is sent.
FAKE_DOCKER = """#!/bin/bash
case "$*" in
    *status=running*) for name in $FAKE_RUNNING; do echo "$name"; done ;;
esac
exit 0
"""
FAKE_CURL = """#!/bin/bash
echo "$*" >> "$FAKE_LOG"
"""


def _watch(scratch: Path, env: str | None, running: str) -> tuple[subprocess.CompletedProcess, str]:
    """Run the watchdog from a scratch checkout: its result and what it posted to Slack."""
    checkout = scratch / "kit"
    script = checkout / "local" / "scripts" / "qdrant_health_check.sh"
    if not script.exists():
        script.parent.mkdir(parents=True)
        shutil.copy(SCRIPT, script)
        (scratch / "fake-bin").mkdir()
        for name, body in (("docker", FAKE_DOCKER), ("curl", FAKE_CURL)):
            (scratch / "fake-bin" / name).write_text(body, encoding="utf-8")
            (scratch / "fake-bin" / name).chmod(0o755)
    if env is not None:
        (checkout / ".env").write_text(env, encoding="utf-8")
    log = scratch / "slack.log"
    log.write_text("", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={
            "PATH": f"{scratch / 'fake-bin'}:{os.environ['PATH']}",
            "TMPDIR": str(scratch),
            "SLACK_WEBHOOK_URL": "https://hooks.invalid/watchdog",
            "FAKE_RUNNING": running,
            "FAKE_LOG": str(log),
        },
    )
    return result, log.read_text(encoding="utf-8")


def test_the_default_instance_is_watched_by_its_default_name(tmp_path):
    result, posted = _watch(tmp_path, None, running="memory-qdrant")
    assert result.returncode == 0 and posted == ""
    assert not list(tmp_path.glob("qdrant_health_check*.down"))


def test_a_kit_on_its_own_port_watches_its_own_container_not_the_default_one(tmp_path):
    # the other kit's Qdrant is up, this kit's is not: the default name must not hide it
    _, posted = _watch(tmp_path, 'QDRANT_PORT="7733"\n', running="memory-qdrant")
    assert "`memory-qdrant-7733` is NOT running" in posted
    assert "container not found" in posted and "bin/install.sh" in posted
    assert (tmp_path / "qdrant_health_check-7733.down").exists()

    _, posted = _watch(tmp_path, None, running="memory-qdrant memory-qdrant-7733")
    assert "`memory-qdrant-7733` is back UP" in posted
    assert not (tmp_path / "qdrant_health_check-7733.down").exists()
