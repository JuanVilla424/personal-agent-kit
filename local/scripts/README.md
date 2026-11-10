# 🛠️ local/scripts

Local scripts for this agent (not to be confused with `scripts/` at the repo root, which holds the
tools behind the pre-commit hooks).

## 📦 Tools

Each subfolder is an independent tool, with its own `README.md`:

| Folder                                                        | What it is                                                                   |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| [`chatterbox-tts-server/`](chatterbox-tts-server/)            | Self-hosted offline TTS fallback (git submodule, upstream — not edited here) |
| [`excel_report_generator/`](excel_report_generator/README.md) | Generates a formatted `.xlsx` from a JSON spec                               |
| [`memory_index/`](memory_index/README.md)                     | Local agent memory client (Qdrant + memory_service)                          |
| [`notify/`](notify/README.md)                                 | Slack bot — party-mode, permissions, TTS voice replies, ops tooling          |
| [`pdf_report_generator/`](pdf_report_generator/README.md)     | Generates a formatted `.pdf` from a JSON spec                                |
