#!/usr/bin/env python3
"""shell_parse.py — read a shell command the way bash will run it, for the guard.

bin/auto_guard.py matches its rules against the text of a command. Bash does not run that text: it
runs what is left after quote removal, escapes and variables, behind wrappers such as `sudo`, plus
whatever is nested in `bash -c`, `eval` or `$(…)`. This module rebuilds that much, so the rules can
also read what bash will run (`normalized`) and the guard can ask about the command's shape
(`walk`).

Tolerant: no input makes it raise. What it cannot read goes to `Script.errors`, and the guard then
grants no exception that needs a clean read. Stdlib only, like the guard: the hooks import it with
any python3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterator

# Nested code deeper than this (substitutions, `bash -c`, `eval`) is not read: the guard treats it
# as code it cannot see.
MAX_DEPTH = 8
# Longer input is not read at all: the text rules still judge it.
MAX_CHARS = 1_000_000

_BLANKS = " \t\r"
_META = " \t\r\n;&|()<>"
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\[[^\]]*\])?\+?=")
_VAR_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
_REDIRECT = re.compile(r"(\d*)(&>>|&>|>>|>\||>&|<<<|<<-|<<|<&|<>|>|<)")
_OPERATORS = ("&&", "||", ";;&", ";;", ";&", "|&", "|", "&", ";", "\n")
# Reserved words that open a compound command: the command proper follows them.
_PREFIX_WORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!"})
# Reserved words that make a header or close a block: their command never runs a program.
_HEADER_WORDS = frozenset({"for", "select", "case", "esac", "fi", "done", "}", "in"})
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "mksh", "ash"})
# `$(which x)`, `$(command -v x)`, `$(type -P x)` and the backtick forms name the program x.
_LOOKUP = re.compile(r"(?:\$\(|`)\s*(?:which|command\s+-v|type\s+-P)\s+([\w.+-]+)\s*(?:\)|`)")

# Programs that run another command: (options that take a value, positional words before it).
_WRAPPERS: dict[str, tuple[frozenset[str], int]] = {
    "sudo": (
        frozenset(
            {
                "-u",
                "-g",
                "-C",
                "-h",
                "-p",
                "-r",
                "-t",
                "-U",
                "-D",
                "-R",
                "-T",
                "--user",
                "--group",
                "--host",
                "--prompt",
                "--role",
                "--type",
                "--other-user",
                "--chdir",
                "--chroot",
                "--command-timeout",
                "--close-from",
            }
        ),
        0,
    ),
    "doas": (frozenset({"-u", "-C"}), 0),
    "env": (frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"}), 0),
    "command": (frozenset(), 0),
    "builtin": (frozenset(), 0),
    "exec": (frozenset({"-a"}), 0),
    "nohup": (frozenset(), 0),
    "nice": (frozenset({"-n", "--adjustment"}), 0),
    "ionice": (frozenset({"-c", "--class", "-n", "--classdata", "-p", "-P", "-u"}), 0),
    "time": (frozenset({"-f", "--format", "-o", "--output"}), 0),
    "timeout": (frozenset({"-s", "--signal", "-k", "--kill-after"}), 1),
    "stdbuf": (frozenset({"-i", "-o", "-e", "--input", "--output", "--error"}), 0),
    "flock": (frozenset({"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"}), 1),
    "xargs": (
        frozenset(
            {
                "-I",
                "-L",
                "-n",
                "-P",
                "-s",
                "-d",
                "-E",
                "-a",
                "--arg-file",
                "--delimiter",
                "--max-args",
                "--max-procs",
                "--max-lines",
                "--max-chars",
                "--replace",
                "--eof",
                "--process-slot-var",
            }
        ),
        0,
    ),
    "setsid": (frozenset(), 0),
    "chroot": (frozenset({"--userspec", "--groups"}), 1),
    "unbuffer": (frozenset(), 0),
    "busybox": (frozenset(), 0),
}

# Options a multi-command CLI accepts before its subcommand, with a separate value. Dropping them
# lets a rule written for `kubectl delete` read `kubectl -n prod delete` too.
_GLOBAL_OPTS: dict[str, frozenset[str]] = {
    "git": frozenset(
        {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env"}
    ),
    "kubectl": frozenset(
        {
            "-n",
            "--namespace",
            "--context",
            "--kubeconfig",
            "-s",
            "--server",
            "--cluster",
            "--user",
            "--token",
            "--as",
            "--as-group",
            "--as-uid",
            "--request-timeout",
            "-v",
            "--v",
            "--cache-dir",
            "--certificate-authority",
            "--client-certificate",
            "--client-key",
            "--tls-server-name",
            "--profile",
            "--profile-output",
            "--log-file",
            "--password",
            "--username",
        }
    ),
    "helm": frozenset(
        {
            "-n",
            "--namespace",
            "--kube-context",
            "--kubeconfig",
            "--registry-config",
            "--repository-cache",
            "--repository-config",
            "--kube-apiserver",
            "--kube-as-user",
            "--kube-as-group",
            "--kube-ca-file",
            "--kube-token",
            "--kube-tls-server-name",
            "--burst-limit",
            "--qps",
            "--content-cache",
        }
    ),
    "docker": frozenset(
        {
            "-H",
            "--host",
            "--context",
            "-c",
            "--config",
            "-l",
            "--log-level",
            "--tlscacert",
            "--tlscert",
            "--tlskey",
        }
    ),
    "podman": frozenset(
        {
            "--connection",
            "-c",
            "--url",
            "--identity",
            "--root",
            "--runroot",
            "--storage-driver",
            "--cgroup-manager",
            "--log-level",
            "--module",
            "--events-backend",
            "--runtime",
            "--tmpdir",
            "--volumepath",
            "--imagestore",
            "--conmon",
            "--hooks-dir",
            "--storage-opt",
            "--ssh",
        }
    ),
    # their one global option, -chdir, is always written -chdir=DIR
    "terraform": frozenset(),
    "tofu": frozenset(),
    "systemctl": frozenset(
        {
            "-H",
            "--host",
            "-M",
            "--machine",
            "--root",
            "--image",
            "-t",
            "--type",
            "-p",
            "--property",
            "-n",
            "--lines",
            "-o",
            "--output",
            "-s",
            "--signal",
            "--kill-whom",
            "--state",
            "--job-mode",
            "--what",
            "--timestamp",
            "--preset-mode",
            "--message",
            "--when",
            "--drop-in",
            "--image-policy",
            "--kill-value",
            "--reboot-argument",
        }
    ),
}
# ssh options that take a value: the first other word is the destination, the rest runs there.
_SSH_VALUE_OPTS = frozenset("BbcDEeFIiJLlmOopQRSWw")
_ANSI_SIMPLE = {
    "a": "\a",
    "b": "\b",
    "e": "\x1b",
    "E": "\x1b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}


# ── The tree ─────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Word:
    """One word, after quote removal and escapes. Expansions stay as written: `$HOME`, `$(…)`."""

    text: str
    start: int  # offsets in the parsed text; meaningful only when `exact`
    end: int
    exact: bool = True  # False inside backticks and nested code, whose source was unescaped
    quoted: bool = False
    expands: bool = False  # it holds a $-expansion or a substitution
    subs: list[Script] = field(default_factory=list)  # the code of its $(…), `…`, <(…), >(…)


@dataclass
class Redirect:
    op: str  # >, >>, <, <<, <<-, <<<, >|, &>, &>>, >&, <&, <>
    target: str  # the target word's text, or a heredoc's delimiter
    word: Word | None = None
    body: str | None = None  # a heredoc's or a here-string's content


@dataclass
class Command:
    words: list[Word] = field(default_factory=list)
    assignments: list[Word] = field(default_factory=list)
    redirects: list[Redirect] = field(default_factory=list)
    body: Script | None = None  # a ( subshell ), a { group } or a function's body
    function: str = ""  # the name, when this command defines a function
    header: bool = False  # `for x in …`, `case … in`, `fi`: a line of syntax, never a program
    nested: list[Script] = field(default_factory=list)  # code it runs: bash -c, eval, -exec…


@dataclass
class Pipeline:
    commands: list[Command]
    op: str  # what follows it: ";", "&", "&&", "||", "\n", ";;" or ""


@dataclass
class Script:
    pipelines: list[Pipeline] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    depth: int = 0
    too_deep: bool = False  # nesting went past MAX_DEPTH somewhere below


@dataclass
class Visit:
    """One command as `walk` meets it."""

    command: Command
    argv: list[str]  # its words, with the variables this command line assigned resolved
    words: list[Word]  # the words of the command that really runs, wrappers dropped
    effective: list[str]  # the same as text: program reduced to its name (`/bin/rm` → `rm`)
    canonical: list[str]  # `effective` without the global options of git, kubectl, docker…
    pipeline: Pipeline
    index: int  # its place in the pipeline
    depth: int  # 0 for the command line itself
    in_substitution: bool  # inside a $(…), `…` or <(…)
    dynamic: bool  # its program is built at run time: the text never names it


# ── Scanning helpers ─────────────────────────────────────────────────────────────────────────────


def _ansi_c(body: str) -> str:
    """The value of $'…': bash's escapes decoded."""
    out: list[str] = []
    i = 0
    while i < len(body):
        c = body[i]
        if c != "\\" or i + 1 >= len(body):
            out.append(c)
            i += 1
            continue
        nxt = body[i + 1]
        if nxt in _ANSI_SIMPLE:
            out.append(_ANSI_SIMPLE[nxt])
            i += 2
            continue
        digits = {"x": (16, 2), "u": (16, 4), "U": (16, 8)}.get(nxt)
        if digits:
            m = re.match(r"[0-9a-fA-F]{1,%d}" % digits[1], body[i + 2 :])
            if m:
                code = int(m.group(0), 16)
                out.append(chr(code) if code <= 0x10FFFF else "")
                i += 2 + len(m.group(0))
                continue
        if nxt in "01234567":
            m = re.match(r"[0-7]{1,3}", body[i + 1 :])
            out.append(chr(int(m.group(0), 8) & 0xFF))  # type: ignore[union-attr]
            i += 1 + len(m.group(0))  # type: ignore[union-attr]
            continue
        if nxt == "c" and i + 2 < len(body):
            out.append(chr(ord(body[i + 2]) & 0x1F))
            i += 3
            continue
        out.append(c + nxt)
        i += 2
    return "".join(out)


def _skip_backtick(src: str, i: int) -> int:
    """Index just past the backtick that closes one opened before `i`, or -1."""
    while i < len(src):
        if src[i] == "\\":
            i += 2
        elif src[i] == "`":
            return i + 1
        else:
            i += 1
    return -1


def _skip_double(src: str, i: int) -> int:
    """Index just past the `"` that closes one opened before `i`, or -1."""
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
        elif c == '"':
            return i + 1
        elif src.startswith("$(", i):
            end = _closing(src, i + 2)
            if end < 0:
                return -1
            i = end + 1
        elif c == "`":
            i = _skip_backtick(src, i + 1)
            if i < 0:
                return -1
        else:
            i += 1
    return -1


def _closing(src: str, i: int, opener: str = "(", closer: str = ")") -> int:
    """Index of the `closer` that balances an `opener` just before `i`, or -1."""
    depth = 1
    while i < len(src):
        c = src[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            end = src.find("'", i + 1)
            if end < 0:
                return -1
            i = end + 1
            continue
        if c == '"':
            i = _skip_double(src, i + 1)
            if i < 0:
                return -1
            continue
        if c == "`":
            i = _skip_backtick(src, i + 1)
            if i < 0:
                return -1
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _basename(text: str) -> str:
    return text.rsplit("/", 1)[-1] if "/" in text else text


# ── The parser ───────────────────────────────────────────────────────────────────────────────────


class _Parser:
    def __init__(self, src: str, base: int, depth: int, exact: bool) -> None:
        self.src = src
        self.n = len(src)
        self.i = 0
        self.base = base
        self.depth = depth
        self.exact = exact
        self.errors: list[str] = []
        self.too_deep = False
        # heredocs whose body starts after the current line: (redirect, the command it feeds)
        self.pending: list[tuple[Redirect, Command, bool]] = []

    # entry points

    def parse(self) -> Script:
        pipelines = self._list(closer="")
        if self.pending:
            self.errors.append("unterminated heredoc")
        return Script(pipelines, self.errors, self.depth, self.too_deep)

    def child(self, text: str, base: int, exact: bool) -> Script:
        """Parse nested code one level deeper; past MAX_DEPTH it is not read."""
        if self.depth + 1 > MAX_DEPTH:
            self.too_deep = True
            return Script(depth=self.depth + 1, too_deep=True)
        script = _Parser(text, base, self.depth + 1, exact).parse()
        self.errors.extend(f"nested: {e}" for e in script.errors)
        self.too_deep = self.too_deep or script.too_deep
        return script

    # lists, pipelines, commands

    def _skip_blanks(self) -> None:
        while self.i < self.n:
            c = self.src[self.i]
            if c in _BLANKS:
                self.i += 1
            elif self.src.startswith("\\\n", self.i):
                self.i += 2
            else:
                return

    def _skip_comment(self) -> None:
        if self.i < self.n and self.src[self.i] == "#":
            end = self.src.find("\n", self.i)
            self.i = self.n if end < 0 else end

    def _operator(self) -> str:
        for op in _OPERATORS:
            if self.src.startswith(op, self.i):
                # `&>` and `&>>` are redirections, not the `&` operator
                if op == "&" and self.src.startswith("&>", self.i):
                    return ""
                return op
        return ""

    def _at_word(self, word: str) -> bool:
        end = self.i + len(word)
        return self.src.startswith(word, self.i) and (end >= self.n or self.src[end] in _META)

    def _list(self, closer: str) -> list[Pipeline]:
        pipelines: list[Pipeline] = []
        while True:
            self._skip_blanks()
            self._skip_comment()
            if self.i >= self.n:
                if closer:
                    self.errors.append(f"missing {closer}")
                return pipelines
            if closer == ")" and self.src[self.i] == ")":
                self.i += 1
                return pipelines
            if closer == "}" and self._at_word("}"):
                self.i += 1
                return pipelines
            op = self._operator()
            if op:  # an empty command: a bare separator
                self.i += len(op)
                if op == "\n":
                    self._read_heredocs()
                continue
            before = self.i
            pipelines.append(self._pipeline(closer))
            if self.i == before:  # nothing could be read here: step over it
                self.errors.append(f"unexpected {self.src[self.i]!r}")
                self.i += 1

    def _pipeline(self, closer: str) -> Pipeline:
        commands: list[Command] = []
        while True:
            commands.append(self._command(closer))
            self._skip_blanks()
            op = self._operator()
            if op in ("|", "|&"):
                self.i += len(op)
                continue
            break
        op = self._operator()
        if op:
            self.i += len(op)
            if op == "\n":
                self._read_heredocs()
        elif self.i < self.n and self.src[self.i] == ")" and closer != ")":
            self.errors.append("unexpected )")  # a case pattern, or broken input
            self.i += 1
            op = ";"
        return Pipeline(commands, op)

    def _command(self, closer: str) -> Command:
        cmd = Command()
        self._skip_blanks()
        if self.src.startswith("((", self.i):  # arithmetic command: nothing runs
            end = self.src.find("))", self.i + 2)
            self.i = self.n if end < 0 else end + 2
            if end < 0:
                self.errors.append("unterminated ((")
            cmd.header = True
            return cmd
        if self.i < self.n and self.src[self.i] == "(":
            self.i += 1
            cmd.body = Script(self._list(closer=")"), depth=self.depth)
            self._trailing_redirects(cmd)
            return cmd
        if self._at_word("{"):
            self.i += 1
            cmd.body = Script(self._list(closer="}"), depth=self.depth)
            self._trailing_redirects(cmd)
            return cmd
        while True:
            self._skip_blanks()
            if self.i >= self.n:
                break
            c = self.src[self.i]
            if c in "<>&0123456789" and self._redirect(cmd):
                continue
            if c in "\n;&|)":
                break
            if c == "(":
                if cmd.words and re.match(r"\(\s*\)", self.src[self.i :]):
                    return self._function(cmd, cmd.words.pop().text, closer)
                self.errors.append("unexpected (")
                self.i += 1
                continue
            if c == "#" and (self.i == 0 or self.src[self.i - 1] in _META):
                self._skip_comment()
                break
            word = self._word()
            if word is None:
                break
            if not cmd.words:
                bare = not word.quoted and not cmd.assignments
                if bare and word.text in _PREFIX_WORDS:
                    continue
                if bare and word.text == "function":
                    return self._function_keyword(cmd, closer)
                # the name must be written bare; the value may be quoted: X='git push'
                if _ASSIGN.match(self.src[word.start - self.base : word.end - self.base]):
                    cmd.assignments.append(word)
                    continue
                if not word.quoted and word.text in _HEADER_WORDS:
                    cmd.header = True
            cmd.words.append(word)
        self._attach_nested(cmd)
        return cmd

    def _function(self, cmd: Command, name: str, closer: str) -> Command:
        self.i = self.src.index(")", self.i) + 1
        self._skip_blanks()
        while self.src.startswith("\n", self.i):
            self.i += 1
            self._skip_blanks()
        body = self._command(closer)
        cmd.function = name
        cmd.body = Script([Pipeline([body], "")], depth=self.depth)
        return cmd

    def _function_keyword(self, cmd: Command, closer: str) -> Command:
        self._skip_blanks()
        name = self._word()
        self._skip_blanks()
        if re.match(r"\(\s*\)", self.src[self.i :]):
            self.i = self.src.index(")", self.i) + 1
        self._skip_blanks()
        body = self._command(closer)
        cmd.function = name.text if name else ""
        cmd.body = Script([Pipeline([body], "")], depth=self.depth)
        return cmd

    def _trailing_redirects(self, cmd: Command) -> None:
        while True:
            self._skip_blanks()
            if not (self.i < self.n and self.src[self.i] in "<>&0123456789"):
                return
            if not self._redirect(cmd):
                return

    # redirections and heredocs

    def _redirect(self, cmd: Command) -> bool:
        m = _REDIRECT.match(self.src, self.i)
        if not m:
            return False
        op = m.group(2)
        if op in ("<", ">") and self.src.startswith("(", m.end()):
            return False  # <(…) and >(…) are process substitutions: words
        self.i = m.end()
        self._skip_blanks()
        word = self._word()
        if word is None:
            self.errors.append(f"redirection {op} without a target")
            return True
        redirect = Redirect(op, word.text, word)
        if op in ("<<", "<<-"):
            self.pending.append((redirect, cmd, op == "<<-"))
        elif op == "<<<":
            redirect.body = word.text
            self._shell_input(cmd, word.text)
        cmd.redirects.append(redirect)
        return True

    def _read_heredocs(self) -> None:
        """Read the bodies of the heredocs opened on the line that just ended."""
        for redirect, owner, strip_tabs in self.pending:
            lines: list[str] = []
            found = False
            while self.i < self.n:
                end = self.src.find("\n", self.i)
                line = self.src[self.i : self.n if end < 0 else end]
                self.i = self.n if end < 0 else end + 1
                if (line.lstrip("\t") if strip_tabs else line) == redirect.target:
                    found = True
                    break
                lines.append(line)
            if not found:
                self.errors.append("unterminated heredoc")
            redirect.body = "\n".join(lines)
            self._shell_input(owner, redirect.body)
        self.pending = []

    def _shell_input(self, cmd: Command, text: str) -> None:
        """A heredoc or here-string fed to a shell is code that shell runs."""
        words = cmd.words[_unwrap([w.text for w in cmd.words]) :]
        if words and _basename(words[0].text) in SHELLS and _shell_code(words) is None:
            cmd.nested.append(self.child(text, 0, exact=False))

    # words

    def _word(self) -> Word | None:
        start = self.i
        out: list[str] = []
        quoted = expands = False
        subs: list[Script] = []
        while self.i < self.n:
            c = self.src[self.i]
            if c in _META:
                if c in "<>" and self.i == start and self.src.startswith("(", self.i + 1):
                    end = _closing(self.src, self.i + 2)
                    if end < 0:
                        self.errors.append("unterminated process substitution")
                        end = self.n - 1
                    subs.append(self._sub(self.i + 2, end, self.exact))
                    out.append(self.src[self.i : end + 1])
                    expands = True
                    self.i = end + 1
                    continue
                so_far = "".join(out)
                if c == "(" and so_far.endswith("=") and _ASSIGN.match(so_far):  # name=(…) array
                    end = _closing(self.src, self.i + 1)
                    end = self.n - 1 if end < 0 else end
                    out.append(self.src[self.i : end + 1])
                    self.i = end + 1
                    continue
                break
            if c == "\\":
                if self.src.startswith("\\\n", self.i):
                    self.i += 2
                    continue
                out.append(self.src[self.i + 1 : self.i + 2])
                quoted = True
                self.i += 2
                continue
            if c == "'":
                end = self.src.find("'", self.i + 1)
                if end < 0:
                    self.errors.append("unterminated '")
                    end = self.n
                out.append(self.src[self.i + 1 : end])
                quoted = True
                self.i = end + 1
                continue
            if c == '"':
                self.i += 1
                quoted = True
                expands |= self._double_quoted(out, subs)
                continue
            if c == "$":
                did_expand, was_quoted = self._dollar(out, subs, in_double=False)
                expands |= did_expand
                quoted |= was_quoted
                continue
            if c == "`":
                self._backtick(out, subs)
                expands = True
                continue
            out.append(c)
            self.i += 1
        if self.i == start:
            return None
        return Word(
            "".join(out), self.base + start, self.base + self.i, self.exact, quoted, expands, subs
        )

    def _double_quoted(self, out: list[str], subs: list[Script]) -> bool:
        expands = False
        while self.i < self.n:
            c = self.src[self.i]
            if c == '"':
                self.i += 1
                return expands
            if c == "\\" and self.i + 1 < self.n:
                nxt = self.src[self.i + 1]
                if nxt in '$`"\\':
                    out.append(nxt)
                elif nxt != "\n":
                    out.append(c + nxt)
                self.i += 2
                continue
            if c == "$":
                expands |= self._dollar(out, subs, in_double=True)[0]
                continue
            if c == "`":
                self._backtick(out, subs)
                expands = True
                continue
            out.append(c)
            self.i += 1
        self.errors.append('unterminated "')
        return expands

    def _dollar(self, out: list[str], subs: list[Script], in_double: bool) -> tuple[bool, bool]:
        """Read one $-form at self.i into `out`: (it expands at run time, it was quoted)."""
        src, i = self.src, self.i
        if not in_double and src.startswith("$'", i):
            end = i + 2
            while end < self.n and src[end] != "'":
                end += 2 if src[end] == "\\" else 1
            if end >= self.n:
                self.errors.append("unterminated $'")
            out.append(_ansi_c(src[i + 2 : min(end, self.n)]))
            self.i = end + 1
            return False, True
        if not in_double and src.startswith('$"', i):
            self.i = i + 2
            return self._double_quoted(out, subs), True
        if src.startswith("$((", i):  # arithmetic: no command runs
            end = _closing(src, i + 2)
            if end < 0:
                self.errors.append("unterminated $((")
                end = self.n
            out.append(src[i : min(end + 1, self.n)])
            self.i = end + 1
            return True, False
        if src.startswith("$(", i):
            end = _closing(src, i + 2)
            if end < 0:
                self.errors.append("unterminated $(")
                end = self.n
            subs.append(self._sub(i + 2, end, self.exact))
            out.append(src[i : min(end + 1, self.n)])
            self.i = end + 1
            return True, False
        if src.startswith("${", i):
            end = _closing(src, i + 2, "{", "}")
            if end < 0:
                self.errors.append("unterminated ${")
                end = self.n
            out.append(src[i : min(end + 1, self.n)])
            self.i = end + 1
            return True, False
        m = re.match(r"\$(?:[A-Za-z_][A-Za-z0-9_]*|[0-9@*#?$!-])", src[i:])
        if m:
            out.append(m.group(0))
            self.i = i + len(m.group(0))
            return True, False
        out.append("$")
        self.i = i + 1
        return False, False

    def _backtick(self, out: list[str], subs: list[Script]) -> None:
        start = self.i
        end = _skip_backtick(self.src, start + 1)
        if end < 0:
            self.errors.append("unterminated `")
            end = self.n + 1
        inner = self.src[start + 1 : end - 1]
        code = re.sub(r"\\([`$\\])", r"\1", inner)
        subs.append(self.child(code, self.base + start + 1, exact=False))
        out.append(self.src[start:end])
        self.i = min(end, self.n)

    def _sub(self, start: int, end: int, exact: bool) -> Script:
        return self.child(self.src[start:end], self.base + start, exact)

    # code a command runs

    def _attach_nested(self, cmd: Command) -> None:
        words = cmd.words[_unwrap([w.text for w in cmd.words]) :]
        if not words:
            return
        prog = _basename(words[0].text)
        code: str | None = None
        if prog in SHELLS:
            code = _shell_code(words)
        elif prog == "su":
            code = _option_value(words[1:], ("-c", "--command"))
        elif prog == "eval":
            code = " ".join(w.text for w in words[1:])
        elif prog == "env":
            code = _option_value(words[1:], ("-S", "--split-string"))
        elif prog == "flock":
            code = _option_value(words[1:], ("-c", "--command"))
        elif prog == "ssh":
            code = _ssh_remote(words[1:])
        if code:
            cmd.nested.append(self.child(code, 0, exact=False))
        if prog == "find":
            for action in _find_actions(words[1:]):
                cmd.nested.append(self.child(action, 0, exact=False))


def _option_value(words: list[Word], names: tuple[str, ...]) -> str | None:
    for i, word in enumerate(words):
        if word.text in names and i + 1 < len(words):
            return words[i + 1].text
        for name in names:
            if name.startswith("--") and word.text.startswith(name + "="):
                return word.text[len(name) + 1 :]
    return None


def _shell_code(words: list[Word]) -> str | None:
    """The code of `bash -c CODE`, `sh -ec CODE`…, or None when the shell reads a file or stdin."""
    i = 1
    while i < len(words):
        text = words[i].text
        if text in ("-o", "+o", "-O", "+O"):
            i += 2  # set and shopt options take a name
            continue
        if text.startswith("--") and text != "--":
            i += 1
            continue
        if not text.startswith(("-", "+")) or text == "--":
            return None  # a script file, or stdin
        if "c" in text[1:]:
            return words[i + 1].text if i + 1 < len(words) else None
        i += 1
    return None


def _ssh_remote(words: list[Word]) -> str | None:
    i = 0
    while i < len(words):
        text = words[i].text
        if text.startswith("-") and len(text) > 1:
            i += 2 if text[-1] in _SSH_VALUE_OPTS and len(text) == 2 else 1
            continue
        rest = [w.text for w in words[i + 1 :]]
        return " ".join(rest) or None
    return None


def _find_actions(words: list[Word]) -> list[str]:
    actions: list[str] = []
    i = 0
    while i < len(words):
        if words[i].text in ("-exec", "-execdir", "-ok", "-okdir"):
            j = i + 1
            while j < len(words) and words[j].text not in (";", "+"):
                j += 1
            actions.append(" ".join(w.text for w in words[i + 1 : j]))
            i = j
        i += 1
    return [a for a in actions if a]


def _after_options(texts: list[str], i: int, wrapper: str) -> int:
    takes_value, positional = _WRAPPERS[wrapper]
    while i < len(texts):
        text = texts[i]
        if text == "--":
            i += 1
            break
        if wrapper == "env" and _ASSIGN.match(text):
            i += 1
            continue
        if text.startswith("-") and text != "-":
            i += 2 if text in takes_value else 1
            continue
        break
    return i + positional


def _unwrap(texts: list[str]) -> int:
    """Index of the word where the command that really runs starts: `sudo nice rm x` → `rm`."""
    start = 0
    for _ in range(12):
        if start >= len(texts):
            return start
        prog = _basename(texts[start])
        if prog not in _WRAPPERS:
            return start
        if prog == "command" and texts[start + 1 : start + 2] in (["-v"], ["-V"]):
            return start
        nxt = _after_options(texts, start + 1, prog)
        if nxt >= len(texts) or texts[nxt].startswith("-"):
            return start  # nothing to run, or `flock FILE -c CMD`: the wrapper is the program
        start = nxt
    return start


def _program(text: str, expands: bool) -> tuple[str, bool]:
    """(the program's name, whether the text leaves it to run time)."""
    lookup = _LOOKUP.fullmatch(text)
    if lookup:
        return lookup.group(1), False
    if expands and ("$" in text or "`" in text):
        tail = text.rsplit("/", 1)[-1]
        if "/" in text and tail and "$" not in tail and "`" not in tail:
            return tail, False  # "$HOME/.local/bin/uv": the name is literal
        return text, True
    return _basename(text), False


def canonical(argv: list[str]) -> list[str]:
    """argv without the options git, kubectl, helm, docker… take before their subcommand."""
    if not argv or argv[0] not in _GLOBAL_OPTS:
        return argv
    takes_value = _GLOBAL_OPTS[argv[0]]
    i = 1
    while i < len(argv) and argv[i].startswith("-") and argv[i] != "--":
        i += 2 if argv[i] in takes_value else 1
    return [argv[0], *argv[i:]] if i > 1 else argv


# ── Reading the tree ─────────────────────────────────────────────────────────────────────────────


def parse(text: str) -> Script:
    """The command line as a tree. Never raises; what it could not read is in `errors`."""
    if len(text) > MAX_CHARS:
        return Script(errors=["too long to read"])
    return _Parser(text, 0, 0, exact=True).parse()


def _resolve(text: str, env: dict[str, str]) -> str:
    if not env or "$" not in text:
        return text
    return _VAR_REF.sub(lambda m: env.get(m.group(1) or m.group(2), m.group(0)), text)


def _assign(cmd: Command, env: dict[str, str]) -> None:
    """Remember the literal values a command line gives its variables: `C=r; ${C}m` reads `rm`."""
    if cmd.words and _basename(cmd.words[0].text) not in (
        "export",
        "declare",
        "typeset",
        "local",
        "readonly",
    ):
        if cmd.words[0].text == "unset":
            for word in cmd.words[1:]:
                env.pop(word.text, None)
        return
    for word in [*cmd.assignments, *cmd.words[1:]]:
        if "=" not in word.text or not _ASSIGN.match(word.text):
            continue
        name, value = word.text.split("=", 1)
        name = name.rstrip("+")
        if word.expands:
            resolved = _resolve(value, env)
            if "$" in resolved or "`" in resolved:
                env.pop(name, None)
                continue
            value = resolved
        env[name] = value


def walk(script: Script) -> Iterator[Visit]:
    """Every command, in order: the line's own, then what each one nests."""
    yield from _walk(script, {}, in_sub=False)


def _walk(script: Script, env: dict[str, str], in_sub: bool) -> Iterator[Visit]:
    for pipeline in script.pipelines:
        for index, cmd in enumerate(pipeline.commands):
            argv = [_resolve(w.text, env) for w in cmd.words]
            start = _unwrap(argv)
            words = cmd.words[start:]
            effective: list[str] = []
            dynamic = False
            if words and not cmd.header:
                program, dynamic = _program(argv[start], words[0].expands)
                effective = [program, *argv[start + 1 :]]
            yield Visit(
                cmd,
                argv,
                words,
                effective,
                canonical(effective),
                pipeline,
                index,
                script.depth,
                in_sub,
                dynamic,
            )
            if cmd.body is not None:
                yield from _walk(cmd.body, env, in_sub)
            for word in [*cmd.assignments, *cmd.words, *(r.word for r in cmd.redirects if r.word)]:
                for sub in word.subs:
                    yield from _walk(sub, dict(env), True)
            for nested in cmd.nested:
                yield from _walk(nested, dict(env), in_sub)
        for cmd in pipeline.commands:
            _assign(cmd, env)


def _line(visit: Visit) -> str:
    cmd = visit.command
    parts = [w.text for w in cmd.assignments] + visit.argv
    for redirect in cmd.redirects:
        parts.append(f"{redirect.op} {redirect.target}")
    return " ".join(parts)


def normalized(script: Script) -> str:
    """The commands bash would run, one pipeline per line: quotes removed, the variables the line
    assigns resolved, then each command again without its wrappers (`sudo`, `env`, `timeout`…) or
    the global options of git, kubectl and the like, then the code nested in it."""
    order: list[int] = []
    groups: dict[int, tuple[list[str], list[str]]] = {}
    for visit in walk(script):
        key = id(visit.pipeline)
        if key not in groups:
            groups[key] = ([], [])
            order.append(key)
        parts, extra = groups[key]
        line = _line(visit)
        if line:
            parts.append(line)
        for form in (visit.effective, visit.canonical):
            text = " ".join(form)
            if text and text != line and text not in extra:
                extra.append(text)
    lines: list[str] = []
    for key in order:
        parts, extra = groups[key]
        if parts:
            lines.append(" | ".join(parts))
        lines.extend(extra)
    return "\n".join(lines)
