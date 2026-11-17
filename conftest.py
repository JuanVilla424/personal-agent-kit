"""Shared test setup: nothing a test does may reach the checkout's own brain page."""

import pytest


@pytest.fixture(scope="session")
def _scratch_bus(tmp_path_factory):
    return tmp_path_factory.mktemp("brain-bus") / "brain_events.jsonl"


@pytest.fixture(autouse=True)
def _pulses_stay_out_of_the_real_bus(_scratch_bus, monkeypatch):
    """The memory service emits a pulse on every save and search, and notes each consolidation
    next to the bus. A test that drives it would write into the bus the real page reads."""
    monkeypatch.setenv("BRAIN_EVENTS_LOG", str(_scratch_bus))
