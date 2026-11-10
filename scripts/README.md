# 🧰 scripts

The tools behind the local hooks in `.pre-commit-config.yaml`. They are part of this repo: edit them
here, and their tests in `tests/` run with the rest of the suite.

| Tool                       | Hook                       | What it does                                   |
| -------------------------- | -------------------------- | ---------------------------------------------- |
| `format_yaml/`             | `yaml-format`              | Formats `.yaml` files                          |
| `format_yml/`              | `yml-format`               | Formats `.yml` files                           |
| `bump_year/`               | `bump-year`                | Updates the year in copyright footers          |
| `generate_changelog/`      | `generate-changelog`       | Generates changelog entries from commits       |
| `control_commit/`          | `validate-commit`          | Validates the commit message and adds its icon |
| `commit_msg_version_bump/` | `commit-msg-version-check` | Bumps the version from a commit keyword        |

Each tool is a single `main.py`. The only third-party dependency is `toml`, declared in
`requirements.dev.txt`.
