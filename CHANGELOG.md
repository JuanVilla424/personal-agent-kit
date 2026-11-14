## [1.0.7] - 2026-11-14

### Chores
- **core**: patch release (`patch candidate`)
- **core**: bump mcp edge-tts and uvicorn requirements
- **core**: bump ruff requirement in notify

### Other Changes
- build(deps): bump charset-normalizer from 3.4.7 to 3.5.2 in /local/scripts/memory_index (#3)
- build(deps): update mypy requirement from <2,>=1.10 to >=2.4.1,<3 in /local/scripts/notify (#4)
- build(deps-dev): update tiktoken requirement from >=0.7.0 to >=0.14.0 (#14)
- build(deps-dev): update black requirement from >=24.3.0 to >=26.10.1 (#13)
- build(deps): bump idna from 3.18 to 3.20 in /local/scripts/memory_index (#5)
- build(deps): bump grpcio from 1.81.1 to 1.85.1 in /local/scripts/memory_index (#1)
- build(deps): bump numpy from 2.5.0 to 2.5.4 in /local/scripts/memory_index (#7)
- build(deps): update fastapi requirement from <1,>=0.111 to >=0.162.4,<1 in /local/scripts/notify (#6)
- build(deps): bump starlette from 1.3.1 to 1.10.0 in /local/scripts/memory_index (#2)
- build(deps): update requests requirement from >=2.31.0 to >=2.34.2 (#12)

## [1.0.6] - 2026-11-14

### Bug Fixes
- **core**: make the tag steps idempotent with the builtin token
- **core**: restore the version controller from the clean template source

### Chores
- **core**: patch release (`patch candidate`)
- **core**: bump version 1.0.5 → 1.0.5 retrigger [no-bump]

## [1.0.5] - 2026-11-14

### Chores
- **core**: bump version 1.0.4 → 1.0.5 (`patch candidate`)

## [1.0.4] - 2026-11-14

### Bug Fixes
- **core**: make the bump check grep based to survive the yaml formatter

### Chores
- **core**: bump version 1.0.2 → 1.0.3 (`patch candidate`)

## [1.0.3] - 2026-11-14

### Features
- **core**: add the native a2a engine with a claude inbox drain
- **core**: add unattended self update with a guard smoke
- **core**: add brain backups and per-task health
- **core**: add personal agent kit

### Bug Fixes
- **core**: name the detached head dev before the update clone
- **core**: clone through the file transport with loud failures
- **core**: unshallow the workspace before the update clone test
- **core**: make the thread cleanup test stale on any machine uptime
- **core**: bump the vulnerable pins and add dependabot

### Documentation
- **core**: add the pull request template
- **core**: add the absolute pr and release rule to the enforcement protocol
- **core**: complete the markdown docs with the house standard

### Chores
- **core**: patch candidate release (`patch candidate`)
- **core**: add the version controller promotion workflow
- **core**: bump version 1.0.1 → 1.0.2
- **core**: bump pytesseract aiosqlite and openpyxl requirements
- **core**: exclude the entrypoint guards from coverage
- **core**: allow manual workflow dispatch

### Other Changes
- build(deps-dev): update pyyaml requirement from >=6.0 to >=6.0.3 (#19)
- build(deps-dev): update pylint requirement from >=3.3.1 to >=4.1.3 (#18)
- build(deps-dev): update prometheus-client requirement (#17)
- build(deps-dev): bump bump2version (#16)
- build(deps): update slack-bolt requirement in /local/scripts/notify (#15)
- build(deps): update pyyaml requirement in /local/scripts/notify (#11)
- build(deps): bump protobuf in /local/scripts/memory_index (#10)
- build(deps): bump annotated-doc in /local/scripts/memory_index (#8)
- build(deps): bump markdown-it-py in /local/scripts/memory_index (#6)
- build(deps): bump actions/checkout from 4 to 7 (#5)
- build(deps): bump actions/setup-python from 5 to 7 (#4)

