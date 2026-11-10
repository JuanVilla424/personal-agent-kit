import re

_FENCE_OPEN = re.compile(r"^```(\w*)", re.MULTILINE)
_FENCE_CLOSE = re.compile(r"^```\s*$", re.MULTILINE)


def _open_fence(text: str) -> str | None:
    opens = _FENCE_OPEN.findall(text)
    closes = _FENCE_CLOSE.findall(text)
    if len(opens) > len(closes):
        return opens[-1] or ""
    return None


def chunk(text: str, max_chars: int = 3800, locale: str = "en") -> list[str]:
    label_reserve = 20
    limit = max_chars - label_reserve
    if len(text) <= limit:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    open_lang: str | None = None

    for para in paragraphs:
        candidate = (current + "\n\n" + para).lstrip() if current else para
        if len(candidate) <= limit:
            current = candidate
            continue

        # Current full — flush it
        if current:
            if open_lang is not None:
                current = current + "\n```"
            chunks.append(current)
            open_lang = _open_fence(current)
            current = ("```" + open_lang + "\n" if open_lang is not None else "") + para
            open_lang = None
        else:
            # Para itself too big — split by lines
            lines = para.split("\n")
            for line in lines:
                candidate = (current + "\n" + line).lstrip() if current else line
                if len(candidate) <= limit:
                    current = candidate
                else:
                    if current:
                        fence = _open_fence(current)
                        if fence is not None:
                            current += "\n```"
                        chunks.append(current)
                        open_lang = fence
                        current = ("```" + open_lang + "\n" if open_lang is not None else "") + line
                        open_lang = None
                    else:
                        # Single line too big — hard split
                        while line:
                            chunks.append(line[:limit])
                            line = line[limit:]

    if current:
        chunks.append(current)

    if len(chunks) <= 1:
        return chunks

    label = "Parte" if locale == "es" else "Part"
    return [f"({label} {i+1}/{len(chunks)})\n{c}" for i, c in enumerate(chunks)]
