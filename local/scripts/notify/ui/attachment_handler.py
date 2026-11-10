import asyncio
import logging
import os
from pathlib import Path

log = logging.getLogger("attachments")

_MAX_BYTES = 25 * 1024 * 1024  # 25 MB


async def process(files: list[dict], bot_token: str) -> str:
    """Process Slack file attachments. Each file dict has: id, name, size, url_private."""
    parts: list[str] = []
    for f in files:
        name = f.get("name", "unknown")
        size = f.get("size", 0)
        url = f.get("url_private", "")

        if size > _MAX_BYTES:
            parts.append(f"[Attachment: {name} — too large ({size // 1024}KB), skipped]")
            continue
        if not url:
            parts.append(f"[Attachment: {name} — URL not available]")
            continue
        try:
            data = await _download(url, bot_token)
            text = await _extract(name, data)
            if text:
                parts.append(f"[Attachment: {name}]\n{text}")
            else:
                parts.append(f"[Attachment: {name} — could not extract text]")
        except Exception as e:
            log.warning("Attachment %s error: %s", name, e)
            parts.append(f"[Attachment: {name} — processing error]")
    return "\n\n".join(parts)


async def _download(url: str, token: str) -> bytes:
    import urllib.parse
    import urllib.request

    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError(f"Unsafe URL scheme: {urllib.parse.urlparse(url).scheme}")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: urllib.request.urlopen(  # nosec B310  # nosemgrep: bandit.B310-1
            req, timeout=30
        ).read(),
    )


async def _extract(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext in (".txt", ".md", ".json", ".yaml", ".yml", ".log", ".csv"):
        try:
            return data.decode("utf-8", errors="replace")[:8000]
        except Exception:
            return ""
    if ext == ".pdf":
        return await asyncio.get_event_loop().run_in_executor(None, _pdf_text, data)
    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return await asyncio.get_event_loop().run_in_executor(None, _ocr_text, data, ext)
    return ""


def _pdf_text(data: bytes) -> str:
    try:
        import pypdf
        import io

        reader = pypdf.PdfReader(io.BytesIO(data))
        texts = []
        for page in reader.pages[:20]:
            texts.append(page.extract_text() or "")
        return "\n".join(texts)[:8000]
    except Exception as e:
        log.debug("PDF extract error: %s", e)
        return ""


def _ocr_text(data: bytes, ext: str) -> str:
    try:
        import pytesseract
        from PIL import Image
        import io

        img = Image.open(io.BytesIO(data))
        return pytesseract.image_to_string(img, lang="spa+eng")[:4000]
    except Exception as e:
        log.debug("OCR error: %s", e)
        return ""
