from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

FILL_DARK = PatternFill(fill_type="solid", fgColor="FF1F4E79", bgColor="FF1F4E79")
FILL_ALT = PatternFill(fill_type="solid", fgColor="FFD6E4F0", bgColor="FFD6E4F0")
FONT_TITLE = Font(name="Calibri", size=13, bold=True, color="FFFFFFFF")
FONT_SECTION = Font(name="Calibri", size=11, bold=True, color="FFFFFFFF")
FONT_SUBTITLE = Font(name="Calibri", size=10, bold=False, color="FFFFFFFF")
FONT_HEADER = Font(name="Calibri", size=10, bold=True, color="FFFFFFFF")
FONT_BODY = Font(name="Calibri", size=10)
ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_LEFT = Alignment(horizontal="left", vertical="center", wrap_text=True)

DEFAULT_WIDTHS = [24, 38, 22, 18, 46, 46, 34, 10, 12, 14, 52]


def _apply_widths(ws, widths: list[int | float]) -> None:
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w


def _merge_row(ws, row: int, col_count: int, text: str, fill, font, height: float = 22) -> None:
    cell = ws.cell(row=row, column=1, value=text)
    cell.fill = fill
    cell.font = font
    cell.alignment = ALIGN_CENTER
    if col_count > 1:
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=col_count)
    ws.row_dimensions[row].height = height


def _write_table(ws, start_row: int, section: dict, col_count: int) -> int:
    headers = section.get("headers", [])
    rows = section.get("rows", [])
    actual_cols = len(headers) if headers else col_count

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col, value=h)
        cell.fill = FILL_DARK
        cell.font = FONT_HEADER
        cell.alignment = ALIGN_CENTER
    ws.row_dimensions[start_row].height = 18

    for r_idx, row_data in enumerate(rows):
        data_row = start_row + 1 + r_idx
        for col_idx, val in enumerate(row_data, 1):
            cell = ws.cell(row=data_row, column=col_idx, value=val)
            cell.font = FONT_BODY
            cell.alignment = ALIGN_LEFT
            if r_idx % 2 == 1:
                cell.fill = FILL_ALT
        ws.row_dimensions[data_row].height = 16

    return start_row + 1 + len(rows)


def _write_kv(ws, start_row: int, section: dict, col_count: int) -> int:
    headers = section.get("headers", ["Parameter", "Recommended value", "Location"])
    pairs = section.get("pairs", [])

    for col, h in enumerate(headers, 1):
        cell = ws.cell(row=start_row, column=col, value=h)
        cell.fill = FILL_DARK
        cell.font = FONT_HEADER
        cell.alignment = ALIGN_CENTER
    ws.row_dimensions[start_row].height = 18

    for r_idx, pair in enumerate(pairs):
        data_row = start_row + 1 + r_idx
        for col_idx, val in enumerate(pair, 1):
            cell = ws.cell(row=data_row, column=col_idx, value=val)
            cell.font = FONT_BODY
            cell.alignment = ALIGN_LEFT
            if r_idx % 2 == 1:
                cell.fill = FILL_ALT
        ws.row_dimensions[data_row].height = 16

    return start_row + 1 + len(pairs)


def _build_sheet(wb: Workbook, sheet_spec: dict) -> None:
    ws = wb.create_sheet(title=sheet_spec["name"])
    widths = sheet_spec.get("column_widths", DEFAULT_WIDTHS)
    _apply_widths(ws, widths)
    col_count = len(widths)

    current_row = 1
    for section in sheet_spec.get("sections", []):
        stype = section.get("type", "")

        if stype == "title":
            _merge_row(
                ws, current_row, col_count, section["text"], FILL_DARK, FONT_TITLE, height=26
            )
            current_row += 1

        elif stype == "subtitle":
            _merge_row(
                ws, current_row, col_count, section["text"], FILL_DARK, FONT_SUBTITLE, height=18
            )
            current_row += 1

        elif stype == "section_title":
            _merge_row(
                ws, current_row, col_count, section["text"], FILL_DARK, FONT_SECTION, height=20
            )
            current_row += 1

        elif stype == "table":
            current_row = _write_table(ws, current_row, section, col_count)

        elif stype == "kv":
            current_row = _write_kv(ws, current_row, section, col_count)

        elif stype == "blank":
            current_row += 1


def build_excel(spec: dict, output: Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)

    for sheet_spec in spec.get("sheets", []):
        _build_sheet(wb, sheet_spec)

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)
    return output
