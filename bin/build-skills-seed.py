#!/usr/bin/env python3
"""build-skills-seed.py — package this box's vetted global Claude Code Skills as an
install-time seed.

Copies a fixed, hand-reviewed allowlist of skills from ~/.claude/skills/ (user-scope,
NOT part of this repo) into bin/skills-seed/, and regenerates bin/skills-seed/MANIFEST.md
documenting what's included and excluded (and why). install.sh copies this seed into a
new engineer's own ~/.claude/skills/ so their agent starts with the same general-purpose
engineering skills (debugging, TDD, code review, planning, skill authoring) this box
already has — these are global/user-scope, so a plain git clone never brings them.

The allowlist is curated by hand (see SKILLS below), not "everything in ~/.claude/skills/":
several installed skills are frontend/UI-design only (out of scope for this backend-only
package) or center on subagent dispatch as their SOLE mechanism (conflicts with
feedback_no_subagents.md) — see EXCLUDED for the specific reasoning per skill. Three
included skills (requesting-code-review, writing-plans, writing-skills) still reference
subagent dispatch as PART of their method; they're included verbatim anyway per explicit
user decision 2026-09-05 — MEMORY.md already carries feedback_no_subagents.md into every
session, so the session is expected to decline that step and do it directly instead.
"""

from pathlib import Path
import shutil

SOURCE_DIR = Path.home() / ".claude/skills"
SEED_DIR = Path(__file__).resolve().parent / "skills-seed"

# name -> one-line reason, shown in MANIFEST.md
SKILLS = {
    "systematic-debugging": "Debugging methodology before proposing fixes.",
    "verification-before-completion": (
        "Requires evidence/commands before claiming 'done' — same philosophy as "
        "feedback_validate_before_responding."
    ),
    "test-driven-development": "TDD before implementing a feature/fix.",
    "receiving-code-review": "Technical rigor when receiving feedback, no blind acceptance.",
    "requesting-code-review": (
        "Checklist before calling something done. Its default mechanism dispatches a "
        "reviewer subagent — see the subagent note below."
    ),
    "writing-plans": (
        "Formalizes a multi-step plan before touching code. One of its 2 execution "
        "paths is subagent-driven — see the subagent note below."
    ),
    "executing-plans": (
        "Executes a saved plan in batches with review checkpoints. Required by "
        "writing-plans (the parallel-session path)."
    ),
    "using-git-worktrees": "Creates isolated worktrees. Hard dependency of executing-plans.",
    "finishing-a-development-branch": (
        "Presents structured options (merge/PR/cleanup) when done — the decision "
        "still belongs to the user."
    ),
    "skill-creator": (
        "Guide for creating/editing new skills — used for bmad-component and "
        "fastapi-project-service."
    ),
    "writing-skills": (
        "Complements skill-creator (Anthropic best practices, persuasion "
        "principles). Its testing methodology recommends subagents as 'REQUIRED' — "
        "see the subagent note below."
    ),
    "find-skills": "Helps discover existing installable skills.",
}

# name -> one-line reason it's NOT included
EXCLUDED = {
    "dispatching-parallel-agents": (
        "Its ONLY purpose is orchestrating subagents in parallel — a direct conflict "
        "with feedback_no_subagents.md, with no alternative path."
    ),
    "subagent-driven-development": "Same reason — executes the plan by delegating to subagents.",
    "using-superpowers": (
        "Forces invoking the Skill tool on EVERY response, even trivial questions — "
        "Claude Code's native skill listing already covers discovery without that "
        "process overhead."
    ),
    "agent-browser": (
        "Redundant — browser automation is already covered by chrome-devtools at "
        "the agent level."
    ),
    "frontend-design": (
        "Out of scope — personal-agent-kit has no frontend (would apply to a "
        "sibling project that has one, with its own CLAUDE.md/installer)."
    ),
    "interface-design": "Same reason (no frontend in this repo).",
    "ui-ux-pro-max": "Same reason (no frontend in this repo).",
    "web-design-guidelines": "Same reason (no frontend in this repo).",
    "vercel-react-best-practices": "Same reason (React/Next.js, no frontend in this repo).",
    "vercel-composition-patterns": "Same reason (React, no frontend in this repo).",
    "vercel-react-native-skills": "Same reason (React Native/Expo, no frontend in this repo).",
}

SUBAGENT_NOTE = (
    "**Note on subagents:** `requesting-code-review`, `writing-plans`, and "
    "`writing-skills` include subagent dispatch as part of their method "
    "(direct dispatch, one of 2 execution paths, and testing methodology "
    "respectively). This conflicts with `feedback_no_subagents.md` (the user always "
    "declines subagents). They're included anyway — explicit user decision, "
    "2026-09-05: MEMORY.md already carries that rule into every session, so when the "
    "skill suggests the dispatch step, the session is expected to decline it and "
    "handle it directly instead, without a subagent."
)


def main() -> None:
    SEED_DIR.mkdir(exist_ok=True)
    lines = ["# Skills seed — included / excluded\n"]
    included = 0
    for name, why in SKILLS.items():
        src = SOURCE_DIR / name
        if not src.is_dir():
            print(f"WARN: {name} does not exist in {SOURCE_DIR}, skipping")
            continue
        dst = SEED_DIR / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        lines.append(f"- **{name}** — {why}")
        included += 1
    lines.append("\n## Deliberately excluded\n")
    for name, why in EXCLUDED.items():
        lines.append(f"- ~~{name}~~ — {why}")
    lines.append(f"\n{SUBAGENT_NOTE}\n")
    (SEED_DIR / "MANIFEST.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"OK: {included} skills packaged into {SEED_DIR}")


if __name__ == "__main__":
    main()
