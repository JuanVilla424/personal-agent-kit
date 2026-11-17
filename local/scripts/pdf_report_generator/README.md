# pdf_report_generator

![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)
![reportlab](https://img.shields.io/badge/reportlab-4.0%2B-orange.svg)

Generates `.pdf` files with corporate formatting from the same JSON spec used by
`excel_report_generator`.

- A4 landscape by default (configurable)
- Table headers in `#1F4E79` with bold white text
- Alternating rows (`#D6E4F0`), automatic word-wrap on long cells
- One page per spec sheet, multiple tables per page
- Output to `~/reports/` + mirror copy to `temp/`

## 🚀 Getting Started

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env
```

## 🖥️ CLI

```bash
venv/bin/python main.py path/to/spec.json
venv/bin/python main.py path/to/spec.json --output /custom/path.pdf
venv/bin/python main.py path/to/spec.json --orientation portrait
venv/bin/python main.py path/to/spec.json --no-copy
```

## 🐍 Python API

```python
from pathlib import Path
from generator import build_pdf

spec = { ... }  # same schema as excel_report_generator

build_pdf(spec, Path("~/reports/my-report-2026-05-30.pdf"), orientation="landscape")
```

## 📋 JSON schema (shared with excel_report_generator)

```json
{
  "filename_base": "report-name-YYYY-MM-DD",
  "title": "Overall title (optional)",
  "sheets": [
    {
      "name": "Sheet/section name",
      "column_widths": [24, 38, 22],
      "sections": [
        { "type": "title", "text": "MAIN TITLE" },
        { "type": "subtitle", "text": "Subtitle or date" },
        { "type": "section_title", "text": "=== SECTION ===" },
        { "type": "blank" },
        {
          "type": "table",
          "headers": ["Col A", "Col B"],
          "rows": [["v1", "v2"]]
        },
        {
          "type": "kv",
          "headers": ["Param", "Value", "Where"],
          "pairs": [["k", "v", "loc"]]
        }
      ]
    }
  ]
}
```

## ⚙️ Environment variables (.env)

| Variable     | Default        | Description                                     |
| ------------ | -------------- | ----------------------------------------------- |
| `OUTPUT_DIR` | `~/reports`    | Main output directory                           |
| `MIRROR_DIR` | repo's `temp/` | Mirror copy (optional — leave empty to disable) |
