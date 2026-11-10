"""Smoke tests for centralizing the root .env and the parents[3] resolution.

The parents[3] test catches a silent bug reported by a teammate: if someone moves
a loader to a different folder, parents[3] stops pointing at the repo root."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
MEM_DIR = REPO / "local" / "scripts" / "memory_index"

LOADERS = [
    "local/scripts/memory_index/config.py",
    "local/scripts/excel_report_generator/main.py",
    "local/scripts/pdf_report_generator/main.py",
]


@pytest.mark.parametrize("rel", LOADERS)
def test_loader_parents3_is_repo_root(rel):
    f = REPO / rel
    assert f.exists(), f"loader does not exist: {rel}"
    # parents[3] of each loader must be the repo root (checked via .env.template).
    assert f.resolve().parents[3] == REPO
    assert (f.resolve().parents[3] / ".env.template").exists()


def _import_config_in_subprocess(extra_env=None):
    code = (
        "import sys; sys.path.insert(0, r'%s'); import config; "
        "print('REPO_ROOT', config.REPO_ROOT); print('QDRANT_HOST', config.QDRANT_HOST)"
        % str(MEM_DIR)
    )
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)


def test_config_reads_root_env():
    r = _import_config_in_subprocess()
    assert r.returncode == 0, r.stderr
    assert f"REPO_ROOT {REPO}" in r.stdout  # parents[3] resolved the root
    assert "QDRANT_HOST" in r.stdout  # config was read


def test_cli_env_overrides_dotenv():
    # override=False → a value set in the environment (CLI) wins over the .env.
    r = _import_config_in_subprocess({"QDRANT_HOST": "cli-host-xyz"})
    assert r.returncode == 0, r.stderr
    assert "QDRANT_HOST cli-host-xyz" in r.stdout
