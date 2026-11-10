import csv
import re
from pathlib import Path

MANIFEST_PATH = (
    Path(__file__).parent.parent.parent.parent.parent / ".bmad" / "_cfg" / "agent-manifest.csv"
)

_STRIP = re.compile(r"\[(?:C|E|TTS)\][^\n]*", re.IGNORECASE)

_RULES_ES = """
Reglas de Party Mode:
1. Selecciona 2-3 agentes relevantes para la pregunta del usuario.
2. Responde en personaje, con el ícono + displayName al inicio de cada bloque.
3. Permite cross-talk entre agentes (pueden citarse o rebatirse).
4. Si el usuario nombra un agente específico, ese agente lidera la respuesta.
5. Mantén respuestas técnicas y accionables; evita el fluff.
6. NO uses Bash, Edit, Write, ni Task — solo Read.
7. Si necesitas leer archivos del repo, hazlo con la herramienta Read disponible.
""".strip()

_RULES_EN = """
Party Mode Rules:
1. Select 2-3 agents relevant to the user's question.
2. Respond in character, with icon + displayName at the start of each block.
3. Allow cross-talk between agents (they may quote or rebut each other).
4. If the user names a specific agent, that agent leads the response.
5. Keep responses technical and actionable; no fluff.
6. Do NOT use Bash, Edit, Write, or Task — Read only.
7. If you need to read repo files, use the available Read tool.
""".strip()


def _load_agents() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    agents = []
    with MANIFEST_PATH.open(encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            name = row.get("displayName", "").strip()
            icon = row.get("icon", "").strip()
            role = row.get("role", "").strip()
            style = row.get("communicationStyle", "").strip()
            principles = _STRIP.sub("", row.get("principles", "")).strip()
            if name:
                agents.append(
                    {
                        "name": name,
                        "icon": icon,
                        "role": role,
                        "style": style,
                        "principles": principles,
                    }
                )
    return agents


def build(user_message: str, locale: str = "en", force_agent: str | None = None) -> tuple[str, str]:
    agents = _load_agents()
    if force_agent:
        matched = [a for a in agents if a["name"].lower() == force_agent.lower()]
        if matched:
            a = matched[0]
            header = (
                f"You are **{a['name']}** {a['icon']}. Respond as this character only.\n"
                f"Role: {a['role']}\nStyle: {a['style']}\nPrinciples: {a['principles']}"
            )
            return header, user_message
    style_label = "Style" if locale == "en" else "Estilo"
    lines = []
    for a in agents:
        line = f"- {a['icon']} **{a['name']}** — {a['role']}"
        if a["style"]:
            line += f". {style_label}: {a['style']}."
        lines.append(line)

    no_manifest = "(no manifest available)" if locale == "en" else "(manifest no disponible)"
    agents_block = "\n".join(lines) if lines else no_manifest
    rules = _RULES_EN if locale == "en" else _RULES_ES
    header = (
        "You are the Party Mode orchestrator. Available agents:"
        if locale == "en"
        else "Eres el orquestador de Party Mode. Agentes disponibles:"
    )

    system_prompt = f"{header}\n\n{agents_block}\n\n{rules}"
    return system_prompt, user_message
