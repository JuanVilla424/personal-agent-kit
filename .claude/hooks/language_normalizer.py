#!/usr/bin/env python3
"""Language normalization for the Claude Code TTS hook.

Not all text handed to this hook comes from Claude's own generated response: Claude
Code's own built-in ``Notification`` messages (e.g. "Claude is waiting for your
input") are hardcoded in English regardless of the user's configured language. This
ensures whatever reaches the TTS engine is in the globally configured
``TTS_LANGUAGE`` (default English, "en") — inferring the source
language with a cheap local heuristic first, and only falling back to a translation
call (same ``claude -p`` + ``PAK_HOOK_RUNNING=1`` pattern already used by
``persona_rewriter.py`` and ``local/hooks/judge_against_agents.py``) when that
heuristic is not confident the text is already correct.

Runs unconditionally, before any optional persona rewrite — a message must be in
the right language before a persona gets to add style to it, and this must still
work when ``TTS_PERSONA`` is unset (no other translation step exists in that case).
"""

import logging
import os
import re
import subprocess
from shutil import which

from text_cleaning import preserves_critical_tokens

MODEL = "claude-haiku-5-5"  # same fast/cheap model as judge_against_agents.py
TIMEOUT_SECONDS = (
    45  # same as persona_rewriter.py — CLI/node startup dominates, not the model
)
DEFAULT_TARGET_LANGUAGE = "en"

# Cheap bag-of-stopwords heuristic — avoids an LLM round trip for the common case
# (Claude's own responses, already in the target language). Only distinguishes
# Spanish vs English, the only two languages this hook actually encounters: Claude's
# own generated text, and Claude Code's own hardcoded English notification strings.
SPANISH_STOPWORDS = {
    "el",
    "la",
    "los",
    "las",
    "de",
    "que",
    "y",
    "en",
    "un",
    "una",
    "es",
    "para",
    "con",
    "no",
    "se",
    "su",
    "por",
    "más",
    "pero",
    "está",
    "esto",
    "esta",
    "del",
}
ENGLISH_STOPWORDS = {
    "the",
    "is",
    "for",
    "and",
    "of",
    "to",
    "in",
    "that",
    "this",
    "with",
    "are",
    "your",
    "waiting",
    "input",
    "you",
    "on",
    "at",
    "be",
    "have",
    "will",
}
WORD_RE = re.compile(r"[a-záéíóúñ]+", re.IGNORECASE)

logger = logging.getLogger(__name__)


def _looks_like_target_language(text: str, target_language: str) -> bool:
    """Cheap heuristic: does this text already look like it's in the target language?

    Only implemented for Spanish vs English — not general multi-language detection.
    Any other configured target language always defers to the translation call
    (this heuristic has nothing to compare against for it).

    Args:
        text: The text to check.
        target_language: The configured target language code (e.g. "es").

    Returns:
        True when there's no reason to believe a translation call is needed.
    """
    if target_language != "es":
        return True
    words = {w.lower() for w in WORD_RE.findall(text)}
    es_hits = len(words & SPANISH_STOPWORDS)
    en_hits = len(words & ENGLISH_STOPWORDS)
    if es_hits == 0 and en_hits == 0:
        return (
            True  # no signal either way (e.g. just a path/number) — don't force a call
        )
    return es_hits >= en_hits


def _ask_claude(prompt: str) -> str:
    """Run the translation prompt through the headless ``claude`` CLI.

    Sets ``PAK_HOOK_RUNNING=1`` on the child so this nested session's own hooks never
    recurse back into this one (same guard used throughout this hook's other
    ``claude -p`` calls).

    Args:
        prompt: The full translation prompt.

    Returns:
        The model's raw stdout, stripped, or ``""`` on any failure or timeout.
    """
    claude = which("claude")
    if not claude:
        return ""
    env = dict(os.environ, PAK_HOOK_RUNNING="1")
    try:
        result = subprocess.run(
            [claude, "-p", prompt, "--model", MODEL],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            env=env,
            check=False,
        )
        return result.stdout.strip()
    except Exception:
        logger.exception("language normalization: claude -p failed or timed out")
        return ""


def ensure_language(text: str, target_language: str = "") -> str:
    """Translate text into the globally configured target language if it isn't already.

    Covers Claude Code's own built-in Notification strings (e.g. "Claude is waiting
    for your input"), hardcoded in English regardless of the user's language.
    Claude's own generated responses are already in the target language and skip the
    translation call entirely via a cheap local heuristic — this never adds latency
    to the common case.

    Args:
        text: The text to check/translate.
        target_language: Defaults to the ``TTS_LANGUAGE`` env var, then "es".

    Returns:
        The text translated into the target language, or the original text
        unchanged if it already looked correct, or the translation call failed,
        timed out, or dropped a critical token (path/flag/number) for any reason.
    """
    if not text:
        return text
    target_language = target_language or os.getenv(
        "TTS_LANGUAGE", DEFAULT_TARGET_LANGUAGE
    )
    if _looks_like_target_language(text, target_language):
        return text
    prompt = (
        f"Translate the following text into the language with code '{target_language}' "
        "if it isn't already in it. Don't add anything, don't explain anything, don't "
        "use quotes or prefixes, don't change file paths/commands/numbers. If it's "
        "already in that language, respond with exactly the same text, unchanged.\n\n"
        f"TEXT:\n{text}\n"
    )
    translated = _ask_claude(prompt).strip()
    if not translated or not preserves_critical_tokens(text, translated):
        logger.warning(
            "language normalization discarded (empty output, timeout, or dropped a "
            "critical token) — using original text instead"
        )
        return text
    logger.info(
        "language normalized %d -> %d chars (target=%s)",
        len(text),
        len(translated),
        target_language,
    )
    return translated
