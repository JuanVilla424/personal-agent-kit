"""Shared text-to-speech safety utilities for the Claude Code TTS hook.

Markdown/symbol cleaning is used by both ``tts_hook.py`` (the initial pass, before
any persona rewrite) and ``persona_rewriter.py`` (a mandatory final pass on the
rewritten text) — a rewrite model asked to restyle text can reintroduce Markdown
(bold headers, etc.) that never existed in the original, so the same cleaning must
run again on its output before synthesis.

The critical-token helpers (paths, CLI flags, numbers) are used by any LLM-based
transformation step — ``persona_rewriter.py`` (style) and ``language_normalizer.py``
(translation) — to mechanically verify that transformation never dropped or altered
something that must survive byte-for-byte, rather than trusting the prompt alone.

Pure standard library only: ``tts_hook.py`` runs under the system ``python3`` from
its own shebang, not the project's ``.venv``.
"""

import os
import re

# Spoken language for the Spanish-only phonetic adjustments below (respellings,
# spoken symbol names). Defaults to English, same as core/i18n.py's detect_locale().
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en")

# Markdown/syntax noise a TTS engine would otherwise spell out symbol by symbol
# ("asterisk", "forward slash", "double-u double-u double-u" for a bare URL).
# Order matters: links before bare URLs (keep the label, drop the address), bold
# before italic (bold's `**` would otherwise be half-consumed by the italic regex),
# paths after inline-code/URL handling (a backtick-wrapped or bare file path is
# still just a path once those have run).
CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
URL_RE = re.compile(r"https?://\S+")
INLINE_CODE_RE = re.compile(r"`([^`]+)`")
# A pure numeric ratio/score ("10/10", "3/4") is not a path — must run BEFORE PATH_RE
# so it claims these first ("10 de 10", not "10 slash 10"). Bounded on both sides so
# it doesn't fire in the middle of something else (a version-like "v10/10x").
RATIO_RE = re.compile(r"(?<!\w)(\d+)/(\d+)(?!\w)")
# A path-like token: 2+ segments (word chars, dots, hyphens) joined by "/", with an
# optional leading "/" for absolute paths. Deliberately requires at least one "/" —
# a bare hyphenated word with no slash (normal prose, e.g. "co-relacionado") is left
# untouched; only genuine paths get their symbols spelled out.
PATH_RE = re.compile(r"(?<![\w./-])/?(?:[\w.-]+/)+[\w.-]+(?![\w./-])")
# English-root loanwords: Spanish TTS treats a leading "h" as silent (correct for
# native Spanish words like "hola", "hacer") — but these borrow English's aspirated
# "h" sound, which Spanish conventionally approximates with "j" (the same swap
# Spanish speakers make out loud). An explicit, narrow list — never a blanket h->j
# rule, which would also wrongly hit real Spanish words.
#
# "hardcode" needs only that swap: its "c" is already followed by "o", which is
# already the correct Spanish spelling for /k/ (as in "cosa") — "jardcodeado" reads
# correctly as-is.
HARDCODE_RE = re.compile(r"\bhardcode\w*", re.IGNORECASE)
# "hack" needs one more fix on top of h->j: Spanish has no "ck" cluster at all, and
# spells the /k/ sound before "e"/"i" as "qu" (as in "jaqueca"), never "c" or "ck".
# "jackeado" (h->j only) read like "yaqueado" — respelling "hack"+e... as "jaqu"+e...
# gives "jaqueado", which reads correctly. Only matches when followed by "e" (the
# verb family: hackear/hackeo/hackeado/hackeando/hacker/...) — a bare "hack" with no
# vowel after it is a separate, rarer case not covered here.
HACK_RE = re.compile(r"\bhack(e\w*)", re.IGNORECASE)

# Whole-word pronunciation overrides for tool/tech names that don't conjugate (no
# suffix family to handle, unlike "hack") — just a word that reads wrong as
# ordinary Spanish text. Confirmed by ear by the user, not guessed. Add new entries
# here as they're reported; no new regex needed per word.
PRONUNCIATION_OVERRIDES = {
    "pylint": "piyilint",
}
OVERRIDE_RE = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in PRONUNCIATION_OVERRIDES) + r")\b",
    re.IGNORECASE,
)
BOLD_RE = re.compile(r"\*\*(.+?)\*\*|__(.+?)__")
ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)([^*]+?)\*(?!\*)|(?<!_)_(?!_)([^_]+?)_(?!_)")
HEADER_RE = re.compile(r"^#{1,6}[ \t]*", re.MULTILINE)
BULLET_RE = re.compile(r"^[ \t]*[-*+][ \t]+", re.MULTILINE)
HR_RE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,})[ \t]*$", re.MULTILINE)
BLOCKQUOTE_RE = re.compile(r"^>[ \t]*", re.MULTILINE)
TABLE_SEPARATOR_RE = re.compile(r"^[ \t]*\|?[ \t:|-]+\|?[ \t]*$", re.MULTILINE)
TABLE_ROW_RE = re.compile(r"^[ \t]*\|.*\|[ \t]*$", re.MULTILINE)

# Tokens that must survive any LLM-based transformation (persona rewrite, language
# translation) byte-for-byte: file/dir paths, CLI flags, numbers.
PATH_TOKEN_RE = re.compile(r"(?:[\w.-]+/)+[\w.-]+|(?<![\w.])/[\w./-]+")
FLAG_TOKEN_RE = re.compile(r"(?<!\w)--?[A-Za-z][\w-]*")
NUMBER_TOKEN_RE = re.compile(r"(?<!\w)\d[\d.,]*(?!\w)")


def _speak_table_row(match: "re.Match[str]") -> str:
    """Convert one Markdown table row into a comma-separated spoken phrase.

    Turns ``| Plugin | Scope |`` into ``Plugin, Scope`` — reading raw pipe
    characters aloud is exactly the kind of symbol noise this hook must avoid.

    Args:
        match: A regex match of one full table row line.

    Returns:
        The row's cells joined with ", ".
    """
    cells = [c.strip() for c in match.group(0).strip().strip("|").split("|")]
    return ", ".join(c for c in cells if c)


def _speak_path(match: "re.Match[str]") -> str:
    """Convert a file-path-like token into a natural spoken phrase.

    Turns ``.claude/hooks/persona.md`` into symbol-free speech: "/" becomes "slash"
    and "-" becomes "dash" ("guion" in Spanish — not "diagonal"/"barra" for a slash,
    which read as robotic symbol-spelling).

    Args:
        match: A regex match of one path-like token (see PATH_RE).

    Returns:
        The token with "/" and "-" replaced by their spoken words.
    """
    dash_word = " guion " if TTS_LANGUAGE == "es" else " dash "
    spoken = match.group(0).replace("/", " slash ").replace("-", dash_word)
    return re.sub(r"\s+", " ", spoken).strip()


def _respell_hardcode(match: "re.Match[str]") -> str:
    """Respell ``hardcode*`` so its "h" sounds like Spanish "j".

    Turns ``hardcodeado`` into ``jardcodeado`` — Spanish's silent-h rule is correct
    for native words, wrong for this borrowed one. Preserves the original
    capitalization of the first letter.

    Args:
        match: A regex match of the ``hardcode`` family (see HARDCODE_RE).

    Returns:
        The same word with its leading "h"/"H" replaced by "j"/"J".
    """
    word = match.group(0)
    return ("J" if word[0].isupper() else "j") + word[1:]


def _respell_hack(match: "re.Match[str]") -> str:
    """Respell the ``hackear`` family so it doesn't read as a foreign "ck" cluster.

    Turns ``hackeado`` into ``jaqueado`` (not ``jackeado``, which reads more like
    "yaqueado") — Spanish has no "ck" digraph; spelling the /k/ sound before "e" as
    "qu" (native orthography, as in "jaqueca") is what actually reads correctly.

    Args:
        match: A regex match of "hack" plus an e-initial suffix (see HACK_RE).

    Returns:
        "jaqu" plus the original suffix, preserving the first letter's case.
    """
    full, suffix = match.group(0), match.group(1)
    return ("J" if full[0].isupper() else "j") + "aqu" + suffix


def _respell_override(match: "re.Match[str]") -> str:
    """Respell a whole word via PRONUNCIATION_OVERRIDES, preserving its first letter's case.

    Args:
        match: A regex match of a known override key (see OVERRIDE_RE).

    Returns:
        The dictionary's respelling, capitalized to match the original.
    """
    word = match.group(0)
    respelled = PRONUNCIATION_OVERRIDES[word.lower()]
    return respelled[0].upper() + respelled[1:] if word[0].isupper() else respelled


def clean_for_speech(text: str) -> str:
    """Strip Markdown and path/URL symbols down to natural spoken language.

    Never truncates — the full text is kept; long responses are read faster
    instead (see ``EdgeTTSEngine``'s speech rate), never cut off with a
    "continues" marker. Only code blocks are dropped, since reading source code
    character by character is noise, not content.

    Must be applied to ANY text before it reaches a TTS engine — including text
    that has already been rewritten by a persona (see ``persona_rewriter.py``),
    since a rewrite model can reintroduce Markdown that was never in the original.

    Args:
        text: Raw text extracted from the hook payload/transcript, or the output
            of a persona rewrite.

    Returns:
        Cleaned text ready for synthesis, in full. Empty if nothing is left to
        say after cleaning.
    """
    text = CODE_BLOCK_RE.sub(
        " se omitió un bloque de código. " if TTS_LANGUAGE == "es" else " a code block was omitted. ",
        text,
    )
    text = TABLE_SEPARATOR_RE.sub(
        "", text
    )  # pure formatting row (|---|---|), zero content
    text = TABLE_ROW_RE.sub(_speak_table_row, text)
    text = LINK_RE.sub(r"\1", text)
    text = URL_RE.sub(" un enlace " if TTS_LANGUAGE == "es" else " a link ", text)
    text = INLINE_CODE_RE.sub(r"\1", text)
    text = RATIO_RE.sub(
        r"\1 de \2" if TTS_LANGUAGE == "es" else r"\1 of \2", text
    )  # "10/10" -> "10 de 10"/"10 of 10", before PATH_RE
    text = PATH_RE.sub(_speak_path, text)
    text = BOLD_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = ITALIC_RE.sub(lambda m: m.group(1) or m.group(2), text)
    text = HEADER_RE.sub("", text)
    text = BULLET_RE.sub("", text)
    text = HR_RE.sub(" ", text)
    text = BLOCKQUOTE_RE.sub("", text)
    if TTS_LANGUAGE == "es":
        text = HARDCODE_RE.sub(_respell_hardcode, text)
        text = HACK_RE.sub(_respell_hack, text)
        text = OVERRIDE_RE.sub(_respell_override, text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def critical_tokens(text: str) -> set:
    """Extract path-like, flag-like, and numeric tokens that must survive a transform."""
    return (
        set(PATH_TOKEN_RE.findall(text))
        | set(FLAG_TOKEN_RE.findall(text))
        | set(NUMBER_TOKEN_RE.findall(text))
    )


def preserves_critical_tokens(original: str, transformed: str) -> bool:
    """Check that every path/flag/number in the original survived a transform verbatim.

    Used by any LLM-based rewrite (persona styling, language translation) to verify
    the model didn't drop or alter something that must stay byte-for-byte identical,
    rather than trusting the prompt's instructions alone.

    Args:
        original: The text before the transform.
        transformed: The model's output.

    Returns:
        False if the transform dropped or altered a path, flag, or number — the
        caller must discard the transform in that case.
    """
    missing = critical_tokens(original) - critical_tokens(transformed)
    return not missing
