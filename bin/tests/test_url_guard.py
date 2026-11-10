"""bin/url_guard.py and its Claude Code hook (local/hooks/url-guard.py), against the URL corpus.

The OpenCode plugin runs the same corpus in .opencode/plugins/tests/url-guard.test.js. No test
resolves a real name: the resolver is replaced, or the case is lexical.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "bin"))

import url_guard as ug  # noqa: E402

CORPUS = [
    json.loads(line)
    for line in (REPO / "evals" / "datasets" / "url-guard-corpus.jsonl").read_text().splitlines()
]
HOOK = REPO / "local" / "hooks" / "url-guard.py"


def public(_host):
    return ["93.184.216.34"]


def _value(case):
    """Token-shaped values are stored in parts, so no secret scanner sees a token in the repo."""
    return "".join(case["parts"]) if "parts" in case else case["value"]


def _args(case):
    key = "url" if case["tool"] == "webfetch" else "query"
    return {key: _value(case)}


@pytest.mark.parametrize("case", CORPUS, ids=lambda c: c["id"])
def test_each_case_gets_its_verdict(case):
    reason = ug.check_tool(case["tool"], _args(case), lookup=public)
    if case["expect"] == "allow":
        assert reason is None
    else:
        assert reason and reason.startswith(ug.PREFIX) and case["why"] in reason


# An allowed fetch resolves its name for real: those stay in-process, with the fake resolver.
HOOK_CASES = [c for c in CORPUS if not (c["expect"] == "allow" and c["tool"] == "webfetch")]


@pytest.mark.parametrize("case", HOOK_CASES, ids=lambda c: c["id"])
def test_the_claude_code_hook_gives_the_same_verdict(case, monkeypatch):
    monkeypatch.delenv("PAK_HOOK_RUNNING", raising=False)
    tool = {"webfetch": "WebFetch", "websearch": "WebSearch"}[case["tool"]]
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"tool_name": tool, "tool_input": _args(case)}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if case["expect"] == "allow":
        assert (proc.returncode, proc.stderr) == (0, "")
    else:
        assert proc.returncode == 2 and case["why"] in proc.stderr


def test_the_corpus_has_both_sides():
    expects = [case["expect"] for case in CORPUS]
    assert expects.count("block") >= 30 and expects.count("allow") >= 15


def test_a_name_that_resolves_to_a_private_address_is_blocked():
    reason = ug.check_url_resolved("https://evil.example.com/x", lambda _h: ["10.0.0.5"])
    assert reason == f"{ug.PREFIX}: evil.example.com resolves to 10.0.0.5, a private address"
    assert ug.check_url_resolved("https://api.example.com/", lambda _h: ["fd00::1%eth0"])
    assert ug.check_url_resolved("https://api.example.com/", lambda _h: ["not-an-ip"]) is None
    assert ug.check_url_resolved("https://api.example.com/", lambda _h: []) is None
    assert ug.check_url_resolved("https://1.1.1.1/", lambda _h: ["10.0.0.1"]) is None


def test_long_inputs_and_empty_ones():
    assert "longer than 512" in ug.check_url("https://example.com/" + "a" * 600)
    assert "longer than 200" in ug.check_query("x" * 201)
    assert ug.check_url("") is None and ug.check_query("  ") is None
    assert ug.check_url_resolved("") is None
    assert "not a valid absolute URL" in ug.check_url("http://[::1")
    assert "not a valid absolute URL" in ug.check_url("https:///path")


def test_other_tools_are_not_its_business():
    assert ug.check_tool("bash", {"command": "curl https://user:pass@example.com"}) is None


def test_the_real_resolver_answers_and_never_hangs(monkeypatch):
    monkeypatch.setattr(ug.socket, "getaddrinfo", lambda *_a: [(2, 1, 6, "", ("127.0.0.1", 0))])
    assert ug._lookup("anything.example") == ["127.0.0.1"]

    def failing(*_args):
        raise OSError("no such host")

    monkeypatch.setattr(ug.socket, "getaddrinfo", failing)
    assert ug._lookup("no-such-host.invalid") == []


def test_the_cli_reads_one_call_and_prints_the_verdict(monkeypatch, capsys):
    import io

    call = {"tool": "websearch", "args": {"query": "token=abc"}}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(call)))
    assert ug.main() == 0
    assert json.loads(capsys.readouterr().out)["allowed"] is False


def test_the_hook_blocks_when_it_cannot_judge(monkeypatch, capsys):
    import importlib.util
    import io

    spec = importlib.util.spec_from_file_location("url_guard_hook", str(HOOK))
    assert spec and spec.loader
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)

    def run(payload):
        monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
        with pytest.raises(SystemExit) as exc:
            hook.main()
        return exc.value.code

    monkeypatch.setenv("PAK_HOOK_RUNNING", "1")
    assert (
        run(json.dumps({"tool_name": "WebFetch", "tool_input": {"url": "http://127.0.0.1/"}})) == 0
    )
    monkeypatch.delenv("PAK_HOOK_RUNNING")
    assert run("{not json") == 0
    monkeypatch.setattr(ug, "check_tool", lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))
    assert run(json.dumps({"tool_name": "WebFetch", "tool_input": {"url": "https://a.b/"}})) == 2
    assert "could not judge" in capsys.readouterr().err
