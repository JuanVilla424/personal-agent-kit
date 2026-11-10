import importlib.util
import json
from pathlib import Path

HOOK_PATH = (
    Path(__file__).resolve().parents[3] / "monitoring" / "hooks" / "push-claude-code-metric.py"
)

spec = importlib.util.spec_from_file_location("hook", HOOK_PATH)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def _write_transcript(tmp_path, entries):
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return str(path)


def _user(text):
    return {"type": "user", "message": {"content": [{"type": "text", "text": text}]}}


def _assistant_text(text):
    return {"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}}


def _assistant_tool(payload):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "input": {"description": payload}}]},
    }


def _tool_result(text):
    return {
        "type": "user",
        "message": {"content": [{"type": "tool_result", "tool_use_id": "x", "content": text}]},
    }


def test_detects_agent_header_in_text(tmp_path):
    path = _write_transcript(
        tmp_path,
        [_user("hello"), _assistant_text("**🔧 Kai (Infra & DevOps):**\n\nDone.")],
    )
    agents, _ = hook.detect_turn_agents(path)
    assert agents == ["Kai"]


def test_ignores_agent_names_inside_tool_payloads(tmp_path):
    path = _write_transcript(
        tmp_path,
        [
            _user("check it"),
            _assistant_tool("docstring with **🎨 Sally (UX):** as an example"),
            _assistant_text("No real headers in this turn."),
        ],
    )
    agents, _ = hook.detect_turn_agents(path)
    assert "Sally" not in agents


def test_tool_results_and_reminders_do_not_reset_turn(tmp_path):
    path = _write_transcript(
        tmp_path,
        [
            _user("hello"),
            _assistant_text("**🎨 Sally (UX):** first part"),
            _tool_result("command output"),
            _user("<system-reminder>injected reminder</system-reminder>"),
            _assistant_text("turn closes with no more headers"),
        ],
    )
    agents, _ = hook.detect_turn_agents(path)
    assert agents == ["Sally"]


def test_falls_back_to_last_command_slug(tmp_path):
    path = _write_transcript(
        tmp_path,
        [
            _user("<command-name>/bmad:core:workflows:party-mode</command-name>"),
            _assistant_text("text with no agent headers"),
        ],
    )
    agents, slug = hook.detect_turn_agents(path)
    assert slug == "party-mode"
    assert agents == ["party-mode"]


def test_new_human_message_resets_previous_turn(tmp_path):
    path = _write_transcript(
        tmp_path,
        [
            _user("hello"),
            _assistant_text("**🔧 Kai (Infra):** old turn"),
            _user("new question"),
            _assistant_text("**🏗️ Winston (Architect):** new turn"),
        ],
    )
    agents, _ = hook.detect_turn_agents(path)
    assert agents == ["Winston"]
