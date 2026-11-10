import re
from pathlib import Path

from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

COLOR_DARK = HexColor("#1F4E79")
COLOR_ALT = HexColor("#EBF2F8")
COLOR_GRID = HexColor("#BBCFE0")

RISK_COLORS = {
    "CRÍTICO": (HexColor("#C00000"), white),
    "RIESGO": (HexColor("#E26B0A"), white),
    "PARCIAL": (HexColor("#F4B942"), black),
    "OK": (HexColor("#70AD47"), white),
    "INTERVENIDO": (HexColor("#2E75B6"), white),
}

# (regex kept for potential future use)
_EMOJI_RE = re.compile(r"[\U0001F300-\U0001F9FF\U00002600-\U000027BF\U00002300-\U000025FF️]+")

_BASE = getSampleStyleSheet()["Normal"]

STYLE_HEADER_CELL = ParagraphStyle(
    "HeaderCell",
    parent=_BASE,
    fontSize=8,
    textColor=white,
    alignment=TA_CENTER,
    fontName="Helvetica-Bold",
    leading=10,
)
STYLE_BODY_CELL = ParagraphStyle(
    "BodyCell",
    parent=_BASE,
    fontSize=7.5,
    alignment=TA_LEFT,
    leading=10,
    wordWrap="LTR",
)
STYLE_RISK_CELL = ParagraphStyle(
    "RiskCell",
    parent=_BASE,
    fontSize=7.5,
    alignment=TA_CENTER,
    leading=10,
    fontName="Helvetica-Bold",
)
STYLE_TITLE_CELL = ParagraphStyle(
    "TitleCell",
    parent=_BASE,
    fontSize=13,
    textColor=white,
    alignment=TA_CENTER,
    fontName="Helvetica-Bold",
    leading=18,
)
STYLE_SUBTITLE_CELL = ParagraphStyle(
    "SubtitleCell",
    parent=_BASE,
    fontSize=9,
    textColor=white,
    alignment=TA_CENTER,
    fontName="Helvetica",
    leading=12,
)
STYLE_SECTION_CELL = ParagraphStyle(
    "SectionCell",
    parent=_BASE,
    fontSize=10,
    textColor=white,
    alignment=TA_LEFT,
    fontName="Helvetica-Bold",
    leading=14,
)


# Latin-1 + useful typography kept by _sanitize
_KEEP_CODEPOINTS = frozenset(range(0x100)) | {
    0x2013,  # en dash –
    0x2014,  # em dash —
    0x2026,  # ellipsis …
    0x2018,
    0x2019,  # curly single quotes
    0x201C,
    0x201D,  # curly double quotes
}


def _sanitize(text: str) -> str:
    """Keep Latin-1 + useful typography; strip all emoji, symbols, pictographs."""
    clean = "".join(c for c in str(text or "") if ord(c) in _KEEP_CODEPOINTS)
    return re.sub(r"  +", " ", clean).strip()


def _detect_risk(text: str) -> str | None:
    """Return risk level key if cell content is a risk indicator, else None."""
    upper = _sanitize(text).upper().strip()
    if "CRITICO" in upper or "CRÍTICO" in upper:
        return "CRÍTICO"
    if "RIESGO" in upper:
        return "RIESGO"
    if "PARCIAL" in upper:
        return "PARCIAL"
    if "INTERVENIDO" in upper:
        return "INTERVENIDO"
    if upper == "OK" or upper.endswith(" OK"):
        return "OK"
    return None


def _banner(text: str, style: ParagraphStyle, page_width: float, height: float) -> Table:
    """Full-width dark-blue banner row for title / subtitle / section heading."""
    t = Table(
        [[Paragraph(_sanitize(text), style)]],
        colWidths=[page_width],
        rowHeights=[height],
    )
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), COLOR_DARK),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return t


def _col_widths_from_spec(sheet_spec: dict, page_width: float) -> list[float] | None:
    """Convert Excel column_widths (char units) to proportional PDF points."""
    excel_widths = sheet_spec.get("column_widths")
    if not excel_widths:
        return None
    total = sum(excel_widths)
    if total == 0:
        return None
    usable = page_width - 2 * mm
    return [w / total * usable for w in excel_widths]


def _build_table_flowable(
    section: dict,
    page_width: float,
    col_widths: list[float] | None = None,
) -> Table:
    # headers_pdf overrides headers for compact column labels in PDF
    headers = section.get("headers_pdf") or section.get("headers", [])
    rows = section.get("rows", [])
    cw = section.get("col_widths_pdf") or col_widths

    if not cw:
        n = max(len(headers), 1)
        cw = [(page_width - 2 * mm) / n] * n

    header_row = [Paragraph(_sanitize(h), STYLE_HEADER_CELL) for h in headers]

    # Detect risk levels per cell BEFORE sanitizing (emojis still present)
    risk_map: dict[tuple[int, int], str] = {}
    for row_idx, row_data in enumerate(rows):
        for col_idx, val in enumerate(row_data):
            risk = _detect_risk(str(val or ""))
            if risk:
                risk_map[(col_idx, row_idx + 1)] = risk  # +1 for header row

    data_rows = [
        [
            Paragraph(
                _sanitize(v),
                STYLE_RISK_CELL if risk_map.get((ci, ri + 1)) else STYLE_BODY_CELL,
            )
            for ci, v in enumerate(row)
        ]
        for ri, row in enumerate(rows)
    ]

    table_data = [header_row] + data_rows

    # Alternating rows (even data rows get light blue)
    alt_rows = [
        ("BACKGROUND", (0, i + 1), (-1, i + 1), COLOR_ALT) for i in range(0, len(data_rows), 2)
    ]

    # Risk color overrides — applied last so they win over alternating
    risk_overrides = []
    for (col_idx, abs_row), risk in risk_map.items():
        bg, fg = RISK_COLORS[risk]
        risk_overrides += [
            ("BACKGROUND", (col_idx, abs_row), (col_idx, abs_row), bg),
            ("TEXTCOLOR", (col_idx, abs_row), (col_idx, abs_row), fg),
        ]

    t = Table(table_data, colWidths=cw, repeatRows=1)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), COLOR_DARK),
                ("TEXTCOLOR", (0, 0), (-1, 0), white),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, COLOR_GRID),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                *alt_rows,
                *risk_overrides,
            ]
        )
    )
    return t


def build_pdf(spec: dict, output: Path, orientation: str = "landscape") -> Path:
    pagesize = landscape(A4) if orientation == "landscape" else A4
    page_width = pagesize[0] - 2 * cm

    output.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(output),
        pagesize=pagesize,
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title=spec.get("title", "Report"),
    )

    story = []
    first_sheet = True

    for sheet in spec.get("sheets", []):
        if not first_sheet:
            story.append(PageBreak())
        first_sheet = False

        sheet_col_widths = _col_widths_from_spec(sheet, page_width)

        for section in sheet.get("sections", []):
            stype = section.get("type", "")

            if stype == "title":
                story.append(_banner(section["text"], STYLE_TITLE_CELL, page_width, 30))

            elif stype == "subtitle":
                story.append(_banner(section["text"], STYLE_SUBTITLE_CELL, page_width, 18))

            elif stype == "section_title":
                story.append(Spacer(1, 3 * mm))
                story.append(_banner(section["text"], STYLE_SECTION_CELL, page_width, 22))

            elif stype == "table":
                story.append(_build_table_flowable(section, page_width, sheet_col_widths))

            elif stype == "kv":
                kv_section = {
                    "headers": section.get(
                        "headers", ["Parameter", "Recommended value", "Location"]
                    ),
                    "headers_pdf": section.get("headers_pdf"),
                    "rows": section.get("pairs", []),
                    "col_widths_pdf": section.get("col_widths_pdf"),
                }
                story.append(_build_table_flowable(kv_section, page_width, sheet_col_widths))

            elif stype == "blank":
                story.append(Spacer(1, 4 * mm))

    doc.build(story)
    return output
