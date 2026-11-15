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
| [`system_report/`](system_report/README.md)                   | Host system report (CPU/mem/disk/procs) — pure stdlib, the reference package |

## 🧰 Develop a new tool

The agent builds new tools for its user on request, following this package layout — the
reference implementation is [`system_report/`](system_report/README.md):

```
local/scripts/<tool>/
├── README.md          # what it is, usage, license line
├── main.py            # the tool (pure stdlib when possible)
└── tests/             # pytest suite — mandatory, CI runs it
```

The workflow: the user describes the need → the agent builds the package → `pytest` green →
one commit (`feat(core): add <tool>`) → push to `dev` → the repo CI validates it again.
Conventions: pure standard library unless a dependency is unavoidable, exit code `0` on
success and `1` on error, every collector/render function unit-tested, house commit format
with the icon added by the `validate-commit` hook.
