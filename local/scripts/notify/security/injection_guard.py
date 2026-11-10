"""Prompt-injection / jailbreak guard for UNTRUSTED TEXT: user messages, tool or CLI output, what a
session is about to store in memory, and the context files a session loads.

Complements ``security/content_filter.py`` — that scans OUTGOING text for secrets; this guards the
INPUT side. Untrusted text can carry instructions that try to override the agent's behavior
("ignore previous instructions", "reveal your system prompt", exfiltrate creds…), hide them where a
human reading the file does not look (an HTML comment), or hide them from the patterns themselves
(zero-width characters between the letters, bidirectional overrides, invisible tag characters).

``scan()`` returns a verdict + the matched signals. Signatures are curated (not user-config) and
weighted; the summed score decides the verdict. Tuned for LOW false positives on normal technical
text — a single strong signal blocks, weaker signals only warn. Stdlib only: the memory service,
bin/scan_context.py and the Slack bot all import it.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum


class Verdict(Enum):
    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"


_SECRET_FILE = (
    r"(?:\.env(?![\w.-])|\.netrc\b|\.npmrc\b|\.pypirc\b|\.pgpass\b|id_rsa(?![\w.-])"
    r"|id_ed25519(?![\w.-])|\.ssh/|/credentials(?![\w.-]))"
)

# (id, weight, regex). Weights sum into a score: >= BLOCK_AT blocks, >= WARN_AT warns.
# Patterns are deliberately specific (require an injection construct, not a common word) so normal
# phrasing ("disregard the previous alert", "show the system status") does NOT trigger.
_SIGNATURES: tuple[tuple[str, int, str], ...] = (
    (
        "override_instructions",
        5,
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,30}\b(previous|prior|above|earlier|all|your)\b"
        r"[^.\n]{0,25}\b(instruction|prompt|rule|guardrail|context|directive)s?\b",
    ),
    (
        "override_instructions",
        5,
        r"\b(ignora|olvida|descarta|omite)\b[^.\n]{0,30}\b(anteriores|previas|tus|todas)\b"
        r"[^.\n]{0,25}\b(instrucci[oó]n|instrucciones|reglas?|indicaci[oó]n|indicaciones|directivas?)\b",
    ),
    (
        "reveal_system_prompt",
        5,
        r"\b(print|reveal|show|repeat|output|reproduce|expose|leak)\b[^.\n]{0,30}"
        r"\b(system prompt|initial instructions|your instructions|system message|your prompt)\b",
    ),
    (
        "persona_override",
        4,
        r"\b(you are now (a |an |going|allowed|free|unrestricted|jailbroken|no longer)"
        r"|from now on,? you (will|must|are|should)|pretend (to be|you (are|have))"
        r"|act as if you (are|were|have no))",
    ),
    (
        "new_instructions",
        4,
        r"(^|\n)\s*(new|updated|real|revised|override|secret|true)\s+"
        r"(instruction|directive|system prompt|rule)s?\s*:",
    ),
    (
        "role_marker_injection",
        4,
        # a heading that is only the role, not "### System requirements"
        r"(<\|im_(start|end)\|>|\[/?(system|assistant|inst)\]|^\s*###\s*(system|instructions?)\s*:?\s*$)",
    ),
    (
        "jailbreak",
        3,
        r"\b(jailbreak|developer mode|dan mode|do anything now"
        r"|without any restrictions|bypass (your |the |all )?(rules|guardrails|safety|filters|restrictions))\b",
    ),
    (
        "exfiltration",
        5,
        # the boundary goes on the word alternatives only: `\b` before `.env` never matched
        r"\b(send|post|exfiltrate|upload|curl|wget|email)\b[^.\n]{0,40}"
        rf"(?:\b(credential|secret|token|api[_ ]?key|password|private key)|{_SECRET_FILE})",
    ),
    (
        "disable_safety",
        5,
        r"\b(ignore|skip|disable|turn off|bypass|forget)\b[^.\n]{0,20}"
        r"\b(approval|confirmation|safety|guardrail|censor|sanitiz)\w*",
    ),
    (
        "secret_file_disclosure",
        4,
        r"\b(print|show|send|upload|post|paste|output|reveal|display|attach|email|share|cat)\b"
        rf"[^.\n]{{0,40}}{_SECRET_FILE}",
    ),
    (
        # An HTML comment does not render: whatever it tells the agent, the human never reads it.
        "hidden_comment",
        3,
        r"<!--(?:(?!-->)[\s\S]){0,2000}?\b(ignore|disregard|override|system prompt|you are now"
        r"|you must|do not (tell|mention|reveal)|exfiltrate|curl|wget)\b",
    ),
)

_COMPILED = tuple(
    (sid, weight, re.compile(rx, re.IGNORECASE | re.MULTILINE)) for sid, weight, rx in _SIGNATURES
)

# Characters a reader does not see. ZWJ (U+200D) is left out: emoji sequences use it.
_INVISIBLE_SIGNATURES: tuple[tuple[str, int, re.Pattern[str]], ...] = (
    ("bidi_override", 5, re.compile("[‪-‮⁦-⁩]")),
    ("invisible_tag_chars", 5, re.compile("[\U000e0000-\U000e007f]")),
    ("zero_width_chars", 3, re.compile("[​‌⁠-⁤᠎­]|(?<!^)﻿")),
)
_HIDING_CHARS = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩᠎­﻿\U000e0000-\U000e007f]")

WARN_AT = 3
BLOCK_AT = 5


@dataclass
class GuardResult:
    verdict: Verdict
    score: int = 0
    signals: list[str] = field(default_factory=list)
    matched: str = ""
    source: str = "input"

    @property
    def is_clean(self) -> bool:
        return self.verdict is Verdict.ALLOW


def _visible(text: str) -> str:
    """The text as the patterns should read it: hiding characters out, look-alike forms folded
    (NFKC turns fullwidth letters into ASCII), so `ig​nore` reads `ignore`."""
    return unicodedata.normalize("NFKC", _HIDING_CHARS.sub("", text))


def scan(text: str, source: str = "input") -> GuardResult:
    """Scan untrusted ``text`` for prompt-injection signals. ``source`` labels its origin
    (input, tool_output, memory, context_file)."""
    if not text:
        return GuardResult(Verdict.ALLOW, source=source)
    score = 0
    signals: list[str] = []
    first_match = ""
    visible = _visible(text)
    checks = [(sid, weight, rx, visible) for sid, weight, rx in _COMPILED]
    checks += [(sid, weight, rx, text) for sid, weight, rx in _INVISIBLE_SIGNATURES]
    for sid, weight, rx, subject in checks:
        m = rx.search(subject)
        if m and sid not in signals:
            score += weight
            signals.append(sid)
            if not first_match:
                first_match = m.group(0).strip()[:80]
    if score >= BLOCK_AT:
        verdict = Verdict.BLOCK
    elif score >= WARN_AT:
        verdict = Verdict.WARN
    else:
        verdict = Verdict.ALLOW
    return GuardResult(
        verdict=verdict, score=score, signals=signals, matched=first_match, source=source
    )
