# Skills seed — included / excluded

- **systematic-debugging** — Debugging methodology before proposing fixes.
- **verification-before-completion** — Requires evidence/commands before claiming 'done' — same philosophy as feedback_validate_before_responding.
- **test-driven-development** — TDD before implementing a feature/fix.
- **receiving-code-review** — Technical rigor when receiving feedback, no blind acceptance.
- **requesting-code-review** — Checklist before calling something done. Its default mechanism dispatches a reviewer subagent — see the subagent note below.
- **writing-plans** — Formalizes a multi-step plan before touching code. One of its 2 execution paths is subagent-driven — see the subagent note below.
- **executing-plans** — Executes a saved plan in batches with review checkpoints. Required by writing-plans (the parallel-session path).
- **using-git-worktrees** — Creates isolated worktrees. Hard dependency of executing-plans.
- **finishing-a-development-branch** — Presents structured options (merge/PR/cleanup) when done — the decision still belongs to the user.
- **skill-creator** — Guide for creating/editing new skills — used for bmad-component and fastapi-project-service.
- **writing-skills** — Complements skill-creator (Anthropic best practices, persuasion principles). Its testing methodology recommends subagents as 'REQUIRED' — see the subagent note below.
- **find-skills** — Helps discover existing installable skills.

## Deliberately excluded

- ~~dispatching-parallel-agents~~ — Its ONLY purpose is orchestrating subagents in parallel — a direct conflict with feedback_no_subagents.md, with no alternative path.
- ~~subagent-driven-development~~ — Same reason — executes the plan by delegating to subagents.
- ~~using-superpowers~~ — Forces invoking the Skill tool on EVERY response, even trivial questions — Claude Code's native skill listing already covers discovery without that process overhead.
- ~~agent-browser~~ — Redundant — browser automation is already covered by chrome-devtools at the agent level.
- ~~frontend-design~~ — Out of scope — personal-agent-kit has no frontend (would apply to a sibling project that has one, with its own CLAUDE.md/installer).
- ~~interface-design~~ — Same reason (no frontend in this repo).
- ~~ui-ux-pro-max~~ — Same reason (no frontend in this repo).
- ~~web-design-guidelines~~ — Same reason (no frontend in this repo).
- ~~vercel-react-best-practices~~ — Same reason (React/Next.js, no frontend in this repo).
- ~~vercel-composition-patterns~~ — Same reason (React, no frontend in this repo).
- ~~vercel-react-native-skills~~ — Same reason (React Native/Expo, no frontend in this repo).

**Note on subagents:** `requesting-code-review`, `writing-plans`, and `writing-skills` include subagent dispatch as part of their method (direct dispatch, one of 2 execution paths, and testing methodology respectively). This conflicts with `feedback_no_subagents.md` (the user always declines subagents). They're included anyway — explicit user decision, 2026-09-05: MEMORY.md already carries that rule into every session, so when the skill suggests the dispatch step, the session is expected to decline it and handle it directly instead, without a subagent.
