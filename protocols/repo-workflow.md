# 🔧 Repo Workflow — full lifecycle

> **Canonical, versioned** procedure for a repo's lifecycle: how to approach a task,
> create/clone, set up, work, commit, **pull/sync**, promote, review, and resolve conflicts.
> This used to live only in memory/the KG (which doesn't travel) → a fresh install didn't have it.
>
> ⚠️ **Lessons learned** do NOT go here — that's a different thing: see `protocols/memory-protocol.md`.
> Applies to personal repos on **GitHub**.

---

## 0. How to approach a task (before touching anything)

1. Read `AGENTS.md` + the applicable protocol (this one, `commit-protocol`, `dependency-management`…).
2. **Understand before changing:** read files in full (not fragments), map the affected area.
3. **Validate before asserting:** never state a cause/fact without real evidence (a command, log, API call).
4. Get on the **correct branch** first (§1). Never work on `main`/`master`.
5. Minimal, focused changes; a single commit per task.
6. When done, **run the FULL suite** (not just the touched module) before pushing.

---

## 1. Correct branch — ALWAYS

- **GitHub** (`github.com/JuanVilla424`): clone and `git checkout dev`.
- **NEVER** work directly on `main` / `master`.

---

## 2. Creating a NEW repo — from a template

NEVER an empty `gh repo create`:

```bash
gh repo create JuanVilla424/<name> --template JuanVilla424/github-cicd-template \
  --private --description "..."
```

To enable the promotion chain on a freshly created repo (§6):

```bash
# Write workflow permissions (without this, the version-controller fails with 403)
gh api -X PUT repos/JuanVilla424/<name>/actions/permissions/workflow \
  -F default_workflow_permissions=write -F can_approve_pull_request_reviews=true
# Create test/prod from main (without them the VC fails with "base invalid")
mainsha=$(gh api repos/JuanVilla424/<name>/git/ref/heads/main -q '.object.sha')
gh api -X POST repos/JuanVilla424/<name>/git/refs -f ref=refs/heads/test -f sha="$mainsha"
gh api -X POST repos/JuanVilla424/<name>/git/refs -f ref=refs/heads/prod -f sha="$mainsha"
```

---

## 3. MANDATORY setup (when cloning or touching a repo for the first time)

In this EXACT order, before any commit:

```bash
git submodule update --init --remote                       # 1. submodules
python3 -m venv .venv                                       # 2. venv at the root — ALWAYS .venv (with the dot)
.venv/bin/pip install -r requirements.txt                  #    runtime (if present)
.venv/bin/pip install -r requirements.dev.txt              #    dev/test: pre-commit, pylint, black, pytest, toml…
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push   # 3. hooks
.venv/bin/pre-commit run --all-files                       # 4. validate
```

- **husky GOTCHA** (web apps): `git config --get core.hooksPath` MUST be empty. If it returns
  `.husky/_`, husky hijacked the hooks → `git config --unset core.hooksPath`, delete `.husky/`,
  remove `prepare:husky`+husky+lint-staged from `package.json`, `pnpm install`, reinstall the hooks.
- **Each repo declares its OWN deps** (runtime → `requirements.txt`; dev/test → `requirements.dev.txt`).
  NEVER depend on a submodule's deps (see `dependency-management.md`).

---

## 4. Working and committing

- Commit format and rules: see `protocols/commit-protocol.md` (a single commit, scope `core`, no emojis).
- **2-step push:** `git push` → the `validate-commit` hook adds the icon and amends → aborts →
  push again. **NEVER** `--force`, `--no-verify`, or skip hooks.

---

## 5. Pull / keeping the branch up to date

```bash
git fetch origin
git pull --rebase origin <branch>      # bring in remote changes without spurious merge commits
# if there are conflicts: resolve them (§8), then git rebase --continue
git submodule update --init --remote   # re-sync submodules if they changed
.venv/bin/pre-commit run --all-files   # re-validate after integrating
```

Before starting work and before pushing: **always** `fetch`/`pull` so you don't diverge from the remote.

---

## 6. Promotion `dev → test → prod → main`

- Triggered by a **`[patch candidate]`** commit (at the end of the message) on `dev`: it bumps the
  version (2x push due to the amend) and `version-controller` opens the `dev→test` PR/MR.
- When each PR/MR is merged, the push to the target branch re-triggers the VC and creates the next one.
- **PR/MR ONLY.** NEVER create/merge promotion PRs by hand, and never `git push origin test|prod|main`.
- The final `prod→main` (or `→ master`) merge is approved and merged by a **human**.
- VC re-runs don't help; if a PR is missing, trigger a **fresh** `[patch candidate]`.

> `[patch candidate]` ONLY when promoting/releasing is explicitly requested — never routinely.

---

## 7. Code review / Merge Request

- Review the full diff before merging; merging into protected branches goes through a PR.
- Squash = **"Do not allow"** on every repo (preserves commits → avoids promotion conflicts).

---

## 8. Conflicts

- **By design these shouldn't happen:** no squash + `CHANGELOG.md merge=union` (`.gitattributes`) →
  promotions don't collide.
- If a conflict still shows up during a promotion (an old branch catching up): **the newer one
  wins** — `git merge -s ours` (our whole tree wins), never `-X ours` (which filters files from the
  other side).
- **NEVER** `git push --force` or `git reset --hard`.

---

## 9. Submodules

- **NEVER** edit files inside a submodule — changes go to its original repo.
- Fix: on its `dev` branch, commit with `[patch candidate]` → CI promotes it on its own. Then, in
  the child repo:
  ```bash
  git submodule update --remote helpers/ai18n && git add helpers/ai18n
  git commit -m "chore(core): bump ai18n submodule to latest"
  ```
