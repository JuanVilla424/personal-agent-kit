# 🔧 Repo Workflow (Ultra)

**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

| Rule                             | Violation                                      | Correct                                                                                             |
| -------------------------------- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Base branch                      | Working/committing directly on `main`/`master` | Always `dev`                                                                                        |
| Empty repo                       | `gh repo create` with no template              | Always `--template JuanVilla424/github-cicd-template`                                               |
| Submodule deps                   | Depending on a submodule's deps                | Each repo declares its OWN deps in its own `requirements*.txt`                                      |
| force / no-verify                | `--force`, `--force-with-lease`, `--no-verify` | Never — fix the root cause instead (2nd push, hook, conflict)                                       |
| Manual promotion                 | Creating/merging a promotion PR by hand        | `[patch candidate]` commit on `dev`, the version-controller creates the PR                          |
| Direct push to a promoted branch | `git push origin test\|prod\|main`             | PR/MR ONLY                                                                                          |
| VC re-run                        | Retrying an old run when a PR is missing       | Trigger a fresh `[patch candidate]`                                                                 |
| Squash merge                     | Allowing squash on any repo                    | Squash = "Do not allow" always (avoids promotion conflicts)                                         |
| Promotion conflict               | `git merge -X ours` (filters files)            | `git merge -s ours` (our whole tree wins)                                                           |
| Editing the submodule            | Modifying files inside a submodule             | Fix in its own repo (its `dev`, `[patch candidate]`), then `submodule update --remote` in the child |

---

## ✅ Rules

**0. Approaching a task:** read `AGENTS.md` + the applicable protocol · understand before
changing · validate with evidence before asserting · correct branch first · 1 commit per task ·
FULL suite before pushing.

**3. Setup (exact order, before any commit):**

```bash
git submodule update --init --remote
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements.dev.txt
.venv/bin/pre-commit install --hook-type pre-commit --hook-type pre-push
.venv/bin/pre-commit run --all-files
```

husky GOTCHA: `git config core.hooksPath` must be empty — if not, purge husky.

**4-5. Commit/pull:** format in `commit-protocol`. `git fetch` + `pull --rebase` +
`submodule update --init --remote` + re-validate, always before working and before pushing.

**6. Promotion `dev→test→prod→main`:** triggered by `[patch candidate]` — ONLY when explicitly
requested, never routinely. The final `prod→main` merge is approved and merged by a human.

**7. Review:** full diff before merging, via PR.

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS

`--force`/`reset --hard` on a shared repo can't be undone. Zero tolerance.
