# excel_report_generator

![Python](https://img.shields.io/badge/Python-3.12%2B-blue.svg)
![openpyxl](https://img.shields.io/badge/openpyxl-3.1%2B-green.svg)

Generates `.xlsx` files with corporate formatting from a declarative JSON spec.

- Merged title with `#1F4E79` background + bold white 13pt text
- Table headers bold 10pt, same color
- Alternating rows, native emoji, configurable column widths
- Multiple sheets — supports `title`, `subtitle`, `section_title`, `table`, `kv`, `blank`
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
venv/bin/python main.py path/to/spec.json --output /custom/path.xlsx
venv/bin/python main.py path/to/spec.json --no-copy
```

## 🐍 Python API

```python
from pathlib import Path
from generator import build_excel

spec = {
    "filename_base": "my-report-2026-05-30",
    "sheets": [
        {
            "name": "Sheet1",
            "column_widths": [24, 38, 22],
            "sections": [
                {"type": "title", "text": "MY REPORT"},
                {"type": "subtitle", "text": "Date: 2026-05-30"},
                {"type": "blank"},
                {"type": "section_title", "text": "=== SECTION A ==="},
                {
                    "type": "table",
                    "headers": ["Col A", "Col B", "Col C"],
                    "rows": [
                        ["data1", "data2", "✅ OK"],
                        ["data3", "data4", "🔴 CRÍTICO"]
                    ]
                },
                {"type": "blank"},
                {
                    "type": "kv",
                    "headers": ["Parameter", "Value", "Location"],
                    "pairs": [
                        ["max-pool-size", "120", "jdbc-connection-pool"],
                        ["timeout", "30", "jdbc-connection-pool"]
                    ]
                }
            ]
        }
    ]
}

build_excel(spec, Path("~/reports/my-report-2026-05-30.xlsx"))
```

## ⚙️ Environment variables (.env)

| Variable     | Default        | Description                                     |
| ------------ | -------------- | ----------------------------------------------- |
| `OUTPUT_DIR` | `~/reports`    | Main output directory                           |
| `MIRROR_DIR` | repo's `temp/` | Mirror copy (optional — leave empty to disable) |
