# Project Creation Roadmap — Global Methodology

Standard process for creating any new project/service.

---

- [ ] 1. Create the repo from a template
- [ ] 2. Create the `dev` branch
- [ ] 3. Modify and delete what the template doesn't need
  - Delete unneeded folders (frontend, cazira, external-resources, src)
  - Move `app/` and `tests/` to the root if they're inside `backend/`
  - Update pyproject.toml: name, version ALWAYS `1.0.3`, license, description, an open email (passinbox)
  - Update README.md keeping the same structure and icons, only adapt the content
  - Adapt LICENSE: ASK the user which license they want, explaining the options (MIT, Apache 2.0, GPL v3, etc.) before changing anything
  - Update INSTALL.md, CONTRIBUTING.md, .github/ISSUE_TEMPLATE/config.yml for the new repo
  - Workflows that don't apply: rename to `<name>.yml.disabled` — NEVER delete
  - PROHIBITED: sed, subagents, heredoc, batching — edit file by file
- [ ] 4. Research the language
- [ ] 5. Research the prompt — how to generate it best, iterating

## Cycle Behavior — MANDATORY

- Every step REQUIRES explicit user approval before moving to the next
- If the user does NOT approve → keep iterating on the same step until approval is obtained
- NEVER assume approval — an explicit "yes" is the only valid signal
- Step 5 (prompt) is perpetual until the user is fully satisfied
