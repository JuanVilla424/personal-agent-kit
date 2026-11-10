# Project Creation Roadmap (Compact) — Global Methodology

> Condensed version of `protocols/project-creation-roadmap.md`. Standard process for creating
> any new project/service.

## Steps

- [ ] 1. Create the repo from a template
- [ ] 2. Create the `dev` branch
- [ ] 3. Adapt the template — **file by file** (sed/subagents/heredoc/batching PROHIBITED):
  - Delete unneeded folders (frontend, cazira, external-resources, src); move `app/`/
    `tests/` to the root if they're under `backend/`
  - `pyproject.toml`: name, version ALWAYS `1.0.3`, license, description, an open email (passinbox)
  - `README.md`: same structure/icons, only adapt the content
  - `LICENSE`: ASK the user which license (MIT, Apache 2.0, GPL v3…) BEFORE changing anything
  - Update `INSTALL.md`, `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/config.yml`
  - A workflow that doesn't apply → rename to `<name>.yml.disabled`, NEVER delete
- [ ] 4. Research the language
- [ ] 5. Research the prompt — iterating until fully satisfied (perpetual step)

## Cycles — MANDATORY

Every step requires explicit user approval before moving to the next. No approval → keep
iterating the same step. **NEVER** assume approval — only an explicit "yes" counts.

## Violation = task halt
