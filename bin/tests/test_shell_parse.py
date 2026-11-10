"""bin/shell_parse.py: the command bash would run, read from the text the guard receives."""

import random
import shlex
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "bin"))

import shell_parse as sp  # noqa: E402


def lines(command: str) -> list[str]:
    return sp.normalized(sp.parse(command)).splitlines()


def visits(command: str) -> list[sp.Visit]:
    return list(sp.walk(sp.parse(command)))


def test_quotes_and_escapes_are_removed():
    assert lines("echo \"a b\" 'c d' e\\ f") == ["echo a b c d e f"]


@pytest.mark.parametrize(
    "command, runs",
    [
        ('"r"m -rf x', "rm -rf x"),
        ("r\\m -rf x", "rm -rf x"),
        ("$'\\x72\\x6d' -rf x", "rm -rf x"),
        ("$'\\162\\155' -rf x", "rm -rf x"),
        ("C=r; ${C}m -rf x", "rm -rf x"),
        ("X='git push'; $X --force origin dev", "git push --force origin dev"),
        ("export T=rm; $T x", "rm x"),
    ],
)
def test_what_the_text_hides_is_read_back(command, runs):
    assert runs in lines(command)


@pytest.mark.parametrize(
    "command, runs",
    [
        ("sudo -u bob nice -n 5 rm -rf x", "rm -rf x"),
        ("timeout -s KILL 60 git push -f", "git push -f"),
        ("env -i PATH=/bin rm x", "rm x"),
        ("xargs -0 -n 1 rm -f", "rm -f"),
        ("nohup /bin/rm -rf x", "rm -rf x"),
        ("command rm x", "rm x"),
    ],
)
def test_wrappers_are_dropped(command, runs):
    assert runs in lines(command)


def test_a_lookup_is_not_a_wrapper():
    assert lines("command -v rm") == ["command -v rm"]


@pytest.mark.parametrize(
    "command, canonical",
    [
        ("git -C ../app -c a=b push --force origin main", "git push --force origin main"),
        ("kubectl -n prod delete pvc data", "kubectl delete pvc data"),
        ("helm --namespace prod uninstall api", "helm uninstall api"),
        ("docker --context remote volume rm pgdata", "docker volume rm pgdata"),
        ("terraform -chdir=infra destroy -auto-approve", "terraform destroy -auto-approve"),
        ("systemctl -H box stop auditd", "systemctl stop auditd"),
    ],
)
def test_global_options_before_the_subcommand_are_dropped(command, canonical):
    assert canonical in lines(command)


@pytest.mark.parametrize(
    "command, nested",
    [
        ("bash -lc 'rm -rf x'", "rm -rf x"),
        ("sh -o pipefail -c 'rm x'", "rm x"),
        ("su - root -c 'rm x'", "rm x"),
        ("eval 'rm -rf x'", "rm -rf x"),
        ("env -S 'rm x'", "rm x"),
        ("flock /tmp/l -c 'rm x'", "rm x"),
        ("ssh -p 22 host 'rm -rf /srv'", "rm -rf /srv"),
        ("find . -name '*.bak' -exec rm -f {} \\;", "rm -f {}"),
        ("bash <<EOF\nrm -rf ./build\nEOF", "rm -rf ./build"),
        ("sh <<< 'rm x'", "rm x"),
        ("echo $(rm -rf x)", "rm -rf x"),
        ("echo `rm x`", "rm x"),
        ("diff <(curl -s a) b", "curl -s a"),
    ],
)
def test_nested_code_is_read(command, nested):
    assert nested in lines(command)


def test_a_heredoc_that_nothing_runs_is_data():
    assert lines("cat <<'EOF' > notes.md\nrm -rf /\nEOF\necho done") == [
        "cat << EOF > notes.md",
        "cat",
        "echo done",
    ]


def test_arithmetic_and_comments_run_nothing():
    assert lines("echo $((1+2)) # rm -rf /") == ["echo $((1+2))"]


def test_a_pipeline_stays_on_one_line():
    assert "curl -s x | bash" in lines('curl -s x | "ba"sh')


@pytest.mark.parametrize(
    "command, runs",
    [
        ("if true; then rm x; fi", "rm x"),
        ('for f in *.log; do rm "$f"; done', "rm $f"),
        ("(cd /tmp && rm x)", "rm x"),
        ("{ rm x; }", "rm x"),
        ('wipe() { rm -rf "$1"; }; wipe ./build', "rm -rf $1"),
        ("function wipe { rm -rf x; }", "rm -rf x"),
    ],
)
def test_compound_commands_are_read(command, runs):
    assert runs in lines(command)


@pytest.mark.parametrize(
    "command, program, dynamic",
    [
        ("$(printf 'r%s' m) -rf b", "$(printf 'r%s' m)", True),
        ("$cmd -rf b", "$cmd", True),
        ("C=$(echo r); ${C}m x", "${C}m", True),
        ('"$HOME/.local/bin/uv" sync', "uv", False),
        ("$(which python3) -V", "python3", False),
        ("/usr/bin/git status", "git", False),
    ],
)
def test_a_program_built_at_run_time_is_flagged(command, program, dynamic):
    visit = [v for v in visits(command) if v.effective][-1 if "=" in command else 0]
    assert (visit.effective[0], visit.dynamic) == (program, dynamic)


def test_nesting_past_the_limit_is_flagged():
    command = "rm x"
    for _ in range(sp.MAX_DEPTH + 2):
        command = "bash -c " + shlex.quote(command)
    assert sp.parse(command).too_deep


@pytest.mark.parametrize(
    "command",
    ["echo 'open", 'echo "open', "echo $(open", "cat <<EOF\nno end", "case $x in a) b;; esac"],
)
def test_broken_input_is_noted_never_raised(command):
    assert sp.parse(command).errors


def test_top_level_words_keep_their_offsets():
    command = "python3 -c 'print(1)' | cat"
    code = visits(command)[0].words[2]
    assert (command[code.start : code.end], code.exact) == ("'print(1)'", True)


def test_input_too_long_is_not_read():
    assert sp.parse("a" * (sp.MAX_CHARS + 1)).errors == ["too long to read"]


def test_no_input_makes_it_raise():
    alphabet = list("ab $(){}[]<>|&;'\"`\\\n#=-cx") + ["$(", "<<", "<(", "${", "$'", "EOF"]
    rng = random.Random(20261109)
    for _ in range(3000):
        text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 40)))
        sp.normalized(sp.parse(text))
