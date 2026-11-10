"""Coverage for local/hooks/install-hooks.py.

`main()` is tested by monkeypatching the module's `SETTINGS` constant to a tmp_path
file — real end-to-end run of the real function, never touching the real
~/.claude/settings.json.
"""

import importlib.util
import json
from pathlib import Path

INSTALL_HOOKS = Path(__file__).resolve().parent.parent / "install-hooks.py"


def _load():
    spec = importlib.util.spec_from_file_location("install_hooks_under_test", INSTALL_HOOKS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


install_hooks = _load()


# ── _without_superseded ──────────────────────────────────────────────────────


def test_without_superseded_drops_matching_command():
    groups = [{"matcher": "Bash", "hooks": [{"command": "/x/check-tokens.sh"}]}]
    assert install_hooks._without_superseded(groups) == []


def test_without_superseded_keeps_group_with_other_survivors():
    groups = [
        {
            "matcher": "Bash",
            "hooks": [{"command": "/x/check-tokens.sh"}, {"command": "/x/rm-guard.sh"}],
        }
    ]
    result = install_hooks._without_superseded(groups)
    assert len(result) == 1
    assert [h["command"] for h in result[0]["hooks"]] == ["/x/rm-guard.sh"]


def test_without_superseded_untouched_when_nothing_matches():
    groups = [{"matcher": "Bash", "hooks": [{"command": "/x/rm-guard.sh"}]}]
    assert install_hooks._without_superseded(groups) == groups


# ── _ensure ───────────────────────────────────────────────────────────────────


def test_ensure_creates_new_matcher_group():
    groups = install_hooks._ensure([], "Bash", "/x/rm-guard.sh", 5000)
    assert groups == [
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": "/x/rm-guard.sh", "timeout": 5000}],
        }
    ]


def test_ensure_appends_to_existing_matcher_group():
    groups = [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "/x/a.sh", "timeout": 1}]}
    ]
    result = install_hooks._ensure(groups, "Bash", "/x/b.sh", 2000)
    assert len(result[0]["hooks"]) == 2
    assert result[0]["hooks"][1]["command"] == "/x/b.sh"


def test_ensure_is_idempotent_for_the_same_command():
    groups = install_hooks._ensure([], "Bash", "/x/rm-guard.sh", 5000)
    result = install_hooks._ensure(groups, "Bash", "/x/rm-guard.sh", 5000)
    assert len(result[0]["hooks"]) == 1


# ── main() — real run against an isolated settings.json ─────────────────────


def test_main_creates_settings_with_all_managed_hooks(tmp_path, monkeypatch, capsys):
    settings_file = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(install_hooks, "SETTINGS", settings_file)
    install_hooks.main()
    assert settings_file.is_file()
    hooks = json.loads(settings_file.read_text())["hooks"]
    assert "PreToolUse" in hooks
    assert "SessionStart" in hooks
    assert "registered" in capsys.readouterr().out
    commands = {
        (group["matcher"], Path(hook["command"]).name)
        for group in hooks["PreToolUse"]
        for hook in group["hooks"]
    }
    assert ("Bash", "auto-guard.py") in commands
    assert ("WebFetch|WebSearch", "url-guard.py") in commands


def test_main_second_run_is_a_noop(tmp_path, monkeypatch, capsys):
    settings_file = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(install_hooks, "SETTINGS", settings_file)
    install_hooks.main()
    first = settings_file.read_text()
    install_hooks.main()
    assert settings_file.read_text() == first
    assert "no changes" in capsys.readouterr().out


def test_main_removes_superseded_hooks_on_existing_settings(tmp_path, monkeypatch):
    settings_file = tmp_path / ".claude" / "settings.json"
    settings_file.parent.mkdir(parents=True)
    settings_file.write_text(
        json.dumps(
            {
                "hooks": {
                    "Bash": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "/old/check-tokens.sh"}],
                        }
                    ]
                }
            }
        )
    )
    monkeypatch.setattr(install_hooks, "SETTINGS", settings_file)
    install_hooks.main()
    hooks = json.loads(settings_file.read_text())["hooks"]
    commands = [h["command"] for group in hooks.get("Bash", []) for h in group["hooks"]]
    assert "/old/check-tokens.sh" not in commands
