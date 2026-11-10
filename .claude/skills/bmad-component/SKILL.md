---
name: bmad-component
description: Use when creating or editing a BMAD component in this project — a local persona agent (.bmad/local/*.txt like Kai/Raven), or a workflow (.bmad/*/workflows/*/workflow.md). Follows the framework's own conventions instead of inventing new fields/sections.
allowed-tools: [Read, Edit, Write, Grep, Glob]
---

# BMAD Components (local persona / workflow)

`.bmad/{core,bmm,cis,bmb}/` is **vendored** content from the upstream BMAD framework — it IS
tracked in git (not gitignored: verified, all 511 files under `.bmad/` travel with the repo),
but it's only edited when genuinely necessary (e.g. the A2A bits in
`party-mode/steps/step-02-*.md`), because a future upgrade of the `bmad` package could silently
overwrite those edits. Anything added there follows the upstream framework's own conventions,
not a made-up style. `.bmad/local/` is 100% ours — no upstream counterpart, no such risk.

## Local persona (`.bmad/local/<name>.txt`)

Before creating one, read the full `.bmad/_cfg/agent-manifest.csv` — it has ONE row per
existing agent (infra/Kai, cybersecurity/Raven, reports/Iris, database/Elena...) with
the exact columns that need to be filled in:

`name, displayName, title, icon, role, identity, communicationStyle, principles, module, path`

- `icon`: a single emoji.
- `identity`: the persona's background/expertise, in prose — look at any existing row
  as a template for tone and length.
- `communicationStyle` + `principles`: short sentences separated by periods, in the same
  register as Kai's/Raven's (direct, pragmatic, no filler).
- `module`: `"local"` for this project's personas (not `bmm`/`cis`/`core`, those belong to
  the framework).
- `path`: `.bmad/local/<name>.txt`.

**Steps:**
1. Write the `.txt` at `.bmad/local/<name>.txt` with those same fields as its structure
   (look at an existing `.txt`, e.g. Kai's or Raven's, and copy the exact shape).
2. Add the matching row to `agent-manifest.csv` — if it isn't added there,
   **party-mode never sees it** (the workflow builds the roster by reading that CSV, not by
   scanning `.bmad/local/`).

## Workflow (`.bmad/<module>/workflows/<name>/workflow.md`)

Real structure (verified against `party-mode/workflow.md`, read it in full as a reference
before writing a new one):
- Frontmatter: `name` + `description` (one line).
- Sections in this order: title + "**Goal:**" + "**Your Role:**", then `##` blocks
  such as `WORKFLOW ARCHITECTURE`, `INITIALIZATION` (config to load, paths), the workflow's
  own logic, and if applicable `WORKFLOW STATES` (tracking frontmatter YAML) and
  `EXIT CONDITIONS`.
- If the workflow has steps split into separate files (`steps/step-01-*.md`), reference
  them with "Load step: `./steps/step-NN-name.md`" — don't inline everything into a single
  file if the module's pattern uses micro-files (see the "micro-file architecture" comment
  in `party-mode/workflow.md`).

**Don't invent new sections outside this pattern** — if something is needed that no
existing workflow has, check 2-3 more workflows from the same module (`bmm`/`cis`/`core`)
before deciding it's genuinely new.
