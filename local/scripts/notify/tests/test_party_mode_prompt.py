import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_force_agent_resolves_from_manifest():
    from core.party_mode_prompt import build, MANIFEST_PATH

    if not MANIFEST_PATH.exists():
        import pytest

        pytest.skip("manifest not available")
    system_prompt, msg = build("What's the risk here?", force_agent="Kai")
    assert "Kai" in system_prompt
    assert "Respond as this character only" in system_prompt
    assert msg == "What's the risk here?"


def test_unknown_force_agent_falls_back_to_orchestrator():
    from core.party_mode_prompt import build

    system_prompt, _ = build("Hola equipo", force_agent="Nobody")
    assert (
        "Party Mode" in system_prompt
        or "orquestador" in system_prompt.lower()
        or "Agentes" in system_prompt
    )


def test_no_force_agent_returns_orchestrator_prompt():
    from core.party_mode_prompt import build

    system_prompt, _ = build("Hola equipo")
    assert (
        "Party Mode" in system_prompt
        or "orquestador" in system_prompt.lower()
        or "Agentes" in system_prompt
    )
