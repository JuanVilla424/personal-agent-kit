# 🔧 Repo Workflow (Compact)

> Condensed version of `protocols/repo-workflow.md`. Essential rules for a repo's lifecycle.
> Applies to personal repos on GitHub.

## Rules

**0. Approaching a task:** read `AGENTS.md` + the applicable protocol · understand before
changing · **validate with evidence before asserting** · correct branch first · 1 commit per
task · FULL suite before pushing.

**1. Branch:** `git checkout dev` · NEVER `main`/`master`.

**2. New repo:** from a template — `gh repo create <n> --template JuanVilla424/github-cicd-template`
(never empty). For promotion: workflow perms set to `write` + create `test`/`prod` branches from `main`.

**3. Setup (in order, before committing):**

```bash
git submodule update --init --remote
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements.dev.txt
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
.venv/bin/pre-commit run --all-files
```

Husky: `git config core.hooksPath` MUST be empty (if not, purge husky). Each repo declares its OWN deps.

**4. Commit/push:** see `commit-protocol` (1 commit, scope `core`, no emojis). Push 2x (the hook
amends the icon and aborts the 1st). NEVER `--force`/`--no-verify`.

**5. Pull:** `git fetch`, `git pull --rebase origin <branch>`, `submodule update --init --remote`
and re-validate. Always fetch/pull before working and before pushing.

**6. Promotion dev→test→prod→main:** triggered by `[patch candidate]` (ONLY when explicitly
requested) → `version-controller` creates the PR/MR. **PR/MR ONLY.** NEVER
`git push origin test|prod|main`. The `prod→main` merge is done by a human. If a PR is missing,
trigger a fresh `[patch candidate]` (not a re-run).

**7. Review:** full diff before merging · Squash = **"Do not allow"** on every repo.

**8. Conflicts:** shouldn't happen (no squash + CHANGELOG `merge=union`). If one occurs: the
newer one wins (`git merge -s ours`, never `-X ours`). NEVER `--force` or `reset --hard`.

**9. Submodules:** NEVER edit inside one. Fix in its own repo (`[patch candidate]`), then in the
child `git submodule update --remote <path> && git add <path> && git commit`.

## Violation = task halt
