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
