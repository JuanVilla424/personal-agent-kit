#!/usr/bin/env python3
"""Persona rewriting layer for the Claude Code TTS hook (Historia B).

Rewrites already-cleaned text in the active persona's voice/tone before synthesis,
using the same headless-Claude pattern already established by
``local/hooks/judge_against_agents.py`` (``claude -p`` + ``PAK_HOOK_RUNNING=1`` so the
nested session's own hooks never recurse back into this one).

Two persona sources are checked, local first: ``persona.local.md`` (gitignored — a
personal persona, or a personal override of a shared one, never committed) and
``persona.md`` (shared, tracked, ships with the repo — includes Nova, the default,
and one persona per BMAD agent for party-mode). ``detect_agent_persona`` picks the
matching BMAD persona automatically when the text contains party-mode's own
speaker-attribution format ("**Kai**: ...", per
``.bmad/core/workflows/party-mode/steps/step-02-discussion-orchestration.md``) —
``TTS_PERSONA`` is the fallback when no agent is detected.

Hard rule (non-negotiable, per docs/stories/tts-hook-persona.md): a persona rewrite may
only change register and phrasing. It must never invent, drop, or alter file paths,
filenames, commands, numbers, or the meaning of a permission question. This is enforced
two ways, not just by asking nicely in the prompt: the prompt states it explicitly, and
``preserves_critical_tokens`` (text_cleaning.py) checks it mechanically afterwards. On
any mismatch, empty output, timeout, or missing persona, the caller gets the original
clean text back untouched — this layer must never be the reason a permission prompt is
misunderstood.
"""

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from shutil import which
from typing import NamedTuple, Optional

from text_cleaning import clean_for_speech, preserves_critical_tokens

HERE = Path(__file__).resolve().parent
PERSONA_FILE = HERE / "persona.md"
PERSONA_LOCAL_FILE = HERE / "persona.local.md"  # gitignored — personal, never shared
MODEL = "claude-haiku-5-5"  # same fast/cheap model as judge_against_agents.py
# 5s (the original plan) is not enough: measured on this box, a trivial one-word `claude
# -p` haiku call alone takes ~7.7s (CLI/node startup dominates, not model latency). Reused
# judge_against_agents.py's own value for the identical claude -p + haiku call — runs in
# a detached background worker, never blocks the calling Claude Code session either way.
TIMEOUT_SECONDS = 45
DEFAULT_PERSONA = "nova"
DEFAULT_VOICE = "en-US-GuyNeural"  # matches EdgeTTSEngine's own default

SECTION_RE = re.compile(r"^##\s+(\S+)\s*$", re.MULTILINE)
FIELD_RE = re.compile(r"^(\w+):\s*(.*)$", re.MULTILINE)

# BMAD agent name -> persona id (lowercase of the display name party-mode prints).
# Grounded in .bmad/local/*.txt's own **Name**/**Icon** fields, not invented.
AGENT_PERSONA_IDS = {
    "Kai": "kai",
    "Raven": "raven",
    "Elena": "elena",
    "Iris": "iris",
}
# Party-mode's own documented format is "[Icon] **[Agent Name]**: [response]" — by the
# time this text reaches here it has already been through clean_for_speech(), which
# strips the ** markers but leaves the name and colon untouched, so a plain name+colon
# search is enough (no need to match the icon or the original bold markup).
AGENT_NAME_RE = re.compile(
    r"\b(" + "|".join(AGENT_PERSONA_IDS) + r")\s*:", re.IGNORECASE
)

logger = logging.getLogger(__name__)


class Persona(NamedTuple):
    """Fields parsed from one ``## <id>`` section of a persona file."""

    id: str
    name: str
    language: str
    tone: str
    formality: str
    verbal_tics: list
    greeting: str
    closing: str
    error_reaction: str
    success_reaction: str
    rate: float
    pitch: int
    voice: str


class RewriteResult(NamedTuple):
    """What a rewrite attempt hands back to the caller."""

    text: str
    rate: Optional[float]
    pitch: Optional[int]
    voice: Optional[str]


def detect_agent_persona(text: str) -> Optional[str]:
    """Detect which BMAD agent (if any) is speaking in a party-mode response.

    Looks for party-mode's own speaker-attribution format ("**Kai**: ...") —
    already stripped of its ``**`` markers by the time text reaches this hook (see
    ``text_cleaning.clean_for_speech``), so a plain name+colon match is enough. Uses
    the FIRST agent name found — a single Claude turn with several agents
    cross-talking is voiced as one persona for the whole response rather than
    re-synthesizing per paragraph, which is a much bigger feature on its own.

    Args:
        text: Already-cleaned text (see ``text_cleaning.clean_for_speech``).

    Returns:
        The matching persona id (e.g. "kai"), or None if no known agent name is
        found — the caller should fall back to ``TTS_PERSONA`` in that case.
    """
    match = AGENT_NAME_RE.search(text)
    if not match:
        return None
    return AGENT_PERSONA_IDS[match.group(1).capitalize()]


def _parse_persona_from(content: str, persona_id: str) -> Optional[Persona]:
    """Parse one ``## <id>`` section out of already-read persona-file content.

    Args:
        content: The full text of a persona file (local or shared).
        persona_id: The section name to look up.

    Returns:
        A populated Persona, or None if that section isn't in this content.
    """
    sections = list(SECTION_RE.finditer(content))
    for i, match in enumerate(sections):
        if match.group(1) != persona_id:
            continue
        end = sections[i + 1].start() if i + 1 < len(sections) else len(content)
        body = content[match.end() : end]
        fields = dict(FIELD_RE.findall(body))
        try:
            verbal_tics = json.loads(fields.get("verbal_tics", "[]"))
        except json.JSONDecodeError:
            verbal_tics = []
        return Persona(
            id=persona_id,
            name=fields.get("name", persona_id),
            language=fields.get("language", "en"),
            tone=fields.get("tone", ""),
            formality=fields.get("formality", ""),
            verbal_tics=verbal_tics,
            greeting=fields.get("greeting", ""),
            closing=fields.get("closing", ""),
            error_reaction=fields.get("error_reaction", ""),
            success_reaction=fields.get("success_reaction", ""),
            rate=float(fields.get("rate") or 1.0),
            pitch=int(float(fields.get("pitch") or 0)),
            voice=fields.get("voice") or DEFAULT_VOICE,
        )
    return None


def _load_persona(persona_id: str) -> Optional[Persona]:
    """Look up a persona, checking the personal file before the shared one.

    ``persona.local.md`` (gitignored) is checked first — it can either fully
    redefine an id that also exists in the shared ``persona.md`` (a personal
    override) or define a brand new one that only exists locally. Falls back to
    ``persona.md`` when the id isn't in the local file (or the local file doesn't
    exist at all, the common case).

    Args:
        persona_id: The ``## <id>`` section name to look up.

    Returns:
        A populated Persona, or None if neither file has that section.
    """
    if PERSONA_LOCAL_FILE.is_file():
        local = _parse_persona_from(
            PERSONA_LOCAL_FILE.read_text(encoding="utf-8"), persona_id
        )
        if local:
            return local
    if not PERSONA_FILE.is_file():
        return None
    return _parse_persona_from(PERSONA_FILE.read_text(encoding="utf-8"), persona_id)


def _build_prompt(persona: Persona, event: str, text: str) -> str:
    """Build the rewrite prompt for the given persona, hook event, and text.

    Args:
        persona: The active persona.
        event: The hook event name (``"Stop"`` or ``"Notification"``) — permission
            prompts and critical events get a stricter, near-literal instruction.
        text: The already Markdown-cleaned text to rewrite.

    Returns:
        The full prompt to send to the headless model.
    """
    strictness = (
        "This is a permission or critical-error message: change ONLY the tone/opening, "
        "the rest of the content stays NEARLY LITERAL, word for word."
        if event == "Notification"
        else "This is a summary or normal response: you can freely rephrase the style "
        "and sentence structure."
    )
    tics = (
        ", ".join(persona.verbal_tics)
        if persona.verbal_tics
        else "(none in particular)"
    )
    greeting_line = (
        f"- If the text lends itself to a greeting or opening, start with something "
        f'like: "{persona.greeting}"\n'
        if persona.greeting
        else ""
    )
    closing_line = (
        f"- ALWAYS, without exception, end the response with something along the "
        f'lines of: "{persona.closing}" (the exact phrase isn\'t required, but the '
        f"closing must match that style — it is not optional).\n"
        if persona.closing
        else ""
    )
    return (
        f"You are {persona.name}, you rewrite text to be synthesized as speech (TTS).\n\n"
        "PERSONALITY:\n"
        f"- Tone: {persona.tone}\n"
        f"- Formality: {persona.formality}\n"
        f"- Filler words you can use naturally (feel free to use more than one if "
        f"the text gives room, but don't force them into every sentence): {tics}\n"
        f"{greeting_line}"
        f"{closing_line}"
        f"- On an error: {persona.error_reaction}\n"
        f"- On a success: {persona.success_reaction}\n\n"
        f"MESSAGE CONTEXT: {strictness}\n\n"
        "HARD, INVIOLABLE RULE:\n"
        "- Never invent, omit, or change file paths, file names, commands, numbers, "
        "IDs, or URLs: they must stay character-for-character identical to the "
        "original.\n"
        "- Never change the meaning of a permission question.\n"
        "- Don't add information that isn't in the original text.\n"
        "- Respond ONLY with the rewritten text. No quotes, no prefixes, no "
        "explanations.\n\n"
        f"ORIGINAL TEXT:\n{text}\n"
    )


def _ask_claude(prompt: str) -> str:
    """Run the rewrite prompt through the headless ``claude`` CLI.

    Sets ``PAK_HOOK_RUNNING=1`` on the child so this nested session's own Stop hook
    never re-triggers the TTS hook recursively (same guard ``judge_against_agents.py``
    uses for the same reason).

    Args:
        prompt: The full rewrite prompt.

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
        logger.exception("persona rewrite: claude -p failed or timed out")
        return ""


def _strip_wrapping(text: str) -> str:
    """Strip a single leading/trailing quote or code-fence pair, if the model added one.

    Args:
        text: Raw model output.

    Returns:
        The text with one layer of wrapping quotes/backticks removed, if present.
    """
    text = text.strip()
    for wrapper in ('"""', "'''", "```", '"', "'"):
        if (
            len(text) > 2 * len(wrapper)
            and text.startswith(wrapper)
            and text.endswith(wrapper)
        ):
            return text[len(wrapper) : -len(wrapper)].strip()
    return text


def rewrite(text: str, event: str, persona_id: str = "") -> RewriteResult:
    """Rewrite text in the active persona's voice, falling back to the original on any doubt.

    Args:
        text: Already Markdown-cleaned text, ready for synthesis.
        event: The hook event name (``"Stop"`` or ``"Notification"``).
        persona_id: The persona to use. Defaults to the ``TTS_PERSONA`` env var, then
            ``DEFAULT_PERSONA``. Callers should generally prefer
            ``detect_agent_persona(text) or os.getenv("TTS_PERSONA", "")`` so a
            party-mode BMAD agent's own voice wins over the configured default.

    Returns:
        A RewriteResult. On any failure, missing persona, or a rewrite that dropped a
        critical token, ``text`` is the original unchanged and ``rate``/``pitch``/
        ``voice`` are all None (meaning: the engine falls back to its own defaults,
        exactly Historia A's behavior).
    """
    if not text:
        return RewriteResult(text=text, rate=None, pitch=None, voice=None)
    persona_id = persona_id or os.getenv("TTS_PERSONA", DEFAULT_PERSONA)
    persona = _load_persona(persona_id)
    if not persona:
        return RewriteResult(text=text, rate=None, pitch=None, voice=None)
    rewritten = _strip_wrapping(_ask_claude(_build_prompt(persona, event, text)))
    if not rewritten or not preserves_critical_tokens(text, rewritten):
        logger.warning(
            "persona '%s' rewrite discarded (empty output or dropped a critical "
            "token) — using clean text instead",
            persona_id,
        )
        return RewriteResult(text=text, rate=None, pitch=None, voice=None)
    # The rewrite model can reintroduce Markdown that never existed in the original
    # (bold headers, etc.) — the critical-token check above needs the raw rewrite
    # (with literal "/" characters) to match paths correctly, so this must run
    # AFTER that check, never before it.
    rewritten = clean_for_speech(rewritten)
    logger.info(
        "persona '%s' rewrote %d -> %d chars for event %s (voice=%s)",
        persona.id,
        len(text),
        len(rewritten),
        event,
        persona.voice,
    )
    return RewriteResult(
        text=rewritten, rate=persona.rate, pitch=persona.pitch, voice=persona.voice
    )
