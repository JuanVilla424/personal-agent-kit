"""Coverage for local/hooks/judge_against_agents.py — loaded by path (hyphen-free
name, but co-located with the hyphenated guard scripts under local/hooks/).

`_ask_claude` is always monkeypatched: these are unit tests for the deterministic
logic around the model call, never a real `claude -p` subprocess.
"""

import importlib.util
import json
from pathlib import Path

JUDGE = Path(__file__).resolve().parent.parent / "judge_against_agents.py"


def _load():
    spec = importlib.util.spec_from_file_location("judge_under_test", JUDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


judge = _load()


# ── _read_head ────────────────────────────────────────────────────────────────


def test_read_head_returns_full_content_under_limit(tmp_path):
    f = tmp_path / "small.py"
    f.write_text("line1\nline2\nline3\n")
    assert judge._read_head(f, max_lines=10) == "line1\nline2\nline3"


def test_read_head_truncates_and_marks_it(tmp_path):
    f = tmp_path / "big.py"
    f.write_text("\n".join(f"line{i}" for i in range(10)))
    head = judge._read_head(f, max_lines=3)
    assert head.startswith("line0\nline1\nline2")
    assert "[truncated: 7 more lines]" in head


# ── _parse_verdict ───────────────────────────────────────────────────────────


def test_parse_verdict_valid_json():
    text = '{"pass": true, "violations": []}'
    assert judge._parse_verdict(text) == {"pass": True, "violations": []}


def test_parse_verdict_extracts_json_from_surrounding_prose():
    text = 'Here is my answer:\n{"pass": false, "violations": [{"rule": "x"}]}\nThanks.'
    verdict = judge._parse_verdict(text)
    assert verdict is not None
    assert verdict["pass"] is False
    assert verdict["violations"][0]["rule"] == "x"


def test_parse_verdict_empty_text_is_none():
    assert judge._parse_verdict("") is None


def test_parse_verdict_no_braces_is_none():
    assert judge._parse_verdict("no json here at all") is None


def test_parse_verdict_malformed_json_is_none():
    assert judge._parse_verdict("{pass: true, broken}") is None


# ── main() gating (no model involved) ───────────────────────────────────────


def test_main_returns_0_without_argv(monkeypatch, capsys):
    monkeypatch.setattr(judge.sys, "argv", ["judge_against_agents.py"])
    assert judge.main() == 0
    assert capsys.readouterr().out == ""


def test_main_returns_0_for_unsupported_suffix(monkeypatch, tmp_path, capsys):
    f = tmp_path / "notes.md"
    f.write_text("# notes")
    monkeypatch.setattr(judge.sys, "argv", ["judge_against_agents.py", str(f)])
    called = {"n": 0}
    monkeypatch.setattr(
        judge, "_ask_claude", lambda *_: called.__setitem__("n", called["n"] + 1) or ""
    )
    assert judge.main() == 0
    assert called["n"] == 0  # never even asked the model
    assert capsys.readouterr().out == ""


def test_main_returns_0_for_missing_file(monkeypatch, tmp_path):
    f = tmp_path / "ghost.py"
    monkeypatch.setattr(judge.sys, "argv", ["judge_against_agents.py", str(f)])
    assert judge.main() == 0


# ── main() with a mocked model backend ──────────────────────────────────────


def test_main_prints_nothing_when_verdict_passes(monkeypatch, tmp_path, capsys):
    f = tmp_path / "ok.py"
    f.write_text("print('hello')\n")
    monkeypatch.setattr(judge, "AGENTS_MD", tmp_path / "AGENTS.md")
    (tmp_path / "AGENTS.md").write_text("rules")
    monkeypatch.setattr(judge.sys, "argv", ["judge_against_agents.py", str(f)])
    monkeypatch.setattr(judge, "_ask_claude", lambda *_: '{"pass": true, "violations": []}')
    assert judge.main() == 0
    assert capsys.readouterr().out == ""


def test_main_prints_additional_context_on_violations(monkeypatch, tmp_path, capsys):
    f = tmp_path / "bad.py"
    f.write_text("codigo_en_espanol = True\n")
    monkeypatch.setattr(judge, "AGENTS_MD", tmp_path / "AGENTS.md")
    (tmp_path / "AGENTS.md").write_text("rules")
    monkeypatch.setattr(judge.sys, "argv", ["judge_against_agents.py", str(f)])
    fake_verdict = json.dumps(
        {
            "pass": False,
            "violations": [{"rule": "code in English", "line": 1, "detail": "use English names"}],
        }
    )
    monkeypatch.setattr(judge, "_ask_claude", lambda *_: fake_verdict)
    assert judge.main() == 0  # never blocks — this hook is non-blocking by design
    out = json.loads(capsys.readouterr().out)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert "code in English" in ctx
    assert "bad.py" in ctx


def test_main_returns_0_when_model_unreachable(monkeypatch, tmp_path, capsys):
    f = tmp_path / "whatever.py"
    f.write_text("x = 1\n")
    monkeypatch.setattr(judge, "AGENTS_MD", tmp_path / "AGENTS.md")
    (tmp_path / "AGENTS.md").write_text("rules")
    monkeypatch.setattr(judge.sys, "argv", ["judge_against_agents.py", str(f)])
    monkeypatch.setattr(judge, "_ask_claude", lambda *_: "")  # no backend reachable
    assert judge.main() == 0
    assert capsys.readouterr().out == ""


# ── _ask_claude: real subprocess against a stub binary ────────────────────────


def _stub_claude(tmp_path, monkeypatch, body):
    stub = tmp_path / "claude"
    stub.write_text(f"#!/bin/sh\n{body}\n")
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path), prepend=":")


def test_ask_claude_returns_stdout_and_marks_the_call_as_a_hook(tmp_path, monkeypatch):
    _stub_claude(tmp_path, monkeypatch, 'echo "$PAK_HOOK_RUNNING $1 $2 $3 $4"')
    assert judge._ask_claude("the prompt") == f"1 -p the prompt --model {judge.MODEL}"


def test_ask_claude_without_the_cli_returns_empty(monkeypatch):
    monkeypatch.setattr(judge, "which", lambda _name: None)
    assert judge._ask_claude("the prompt") == ""


def test_ask_claude_that_hangs_returns_empty(tmp_path, monkeypatch):
    _stub_claude(tmp_path, monkeypatch, "sleep 5")
    monkeypatch.setattr(judge, "TIMEOUT_S", 0.05)
    assert judge._ask_claude("the prompt") == ""


def test_main_returns_0_when_the_file_cannot_be_read(monkeypatch, tmp_path, capsys):
    target = tmp_path / "x.py"
    target.write_text("print('x')\n")
    agents_md = tmp_path / "AGENTS.md"
    agents_md.write_text("rules")

    def unreadable(_path, _max_lines):
        raise OSError("gone")

    monkeypatch.setattr(judge, "AGENTS_MD", agents_md)
    monkeypatch.setattr(judge, "_read_head", unreadable)
    monkeypatch.setattr(judge.sys, "argv", ["judge", str(target)])

    assert judge.main() == 0
    assert capsys.readouterr().out == ""
