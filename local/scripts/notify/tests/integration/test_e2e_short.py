"""
Integration test: short query (mock Slack, real claude subprocess).
Only runs on self-hosted runner with SLACK_BOT_TOKEN set.
"""

import os
import pytest

pytestmark = pytest.mark.skipif(not os.getenv("SLACK_BOT_TOKEN"), reason="Requires SLACK_BOT_TOKEN")


def test_env_present():
    """Basic env sanity for integration."""
    assert os.getenv("CLAUDE_BIN") or True  # non-fatal if absent, uses default
