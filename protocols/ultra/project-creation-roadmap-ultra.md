# 🆕 Project Creation Roadmap (Ultra)

**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

| Rule                   | Violation                                           | Correct                                                  |
| ---------------------- | --------------------------------------------------- | -------------------------------------------------------- |
| Assuming approval      | Moving to the next step with no clear confirmation  | Only an explicit "yes" allows moving forward             |
| Mass editing           | `sed`, subagents, heredoc, or batching in step 3    | Edit file by file                                        |
| LICENSE without asking | Choosing/changing the license on your own           | ASK about the options (MIT, Apache 2.0, GPL v3…) first   |
| Deleting a workflow    | Removing a `.yml` that doesn't apply to the project | Rename to `<name>.yml.disabled`                          |
| Empty repo             | `gh repo create` with no template                   | Always from `github-cicd-template` (see `repo-workflow`) |

---

## ✅ Rules

**Steps (each requires explicit approval before the next):**

1. Create the repo from a template
2. Create the `dev` branch
3. Adapt the template, file by file:
   - Delete unneeded folders (frontend, cazira, external-resources, src); move `app/`/
     `tests/` to the root if they're under `backend/`
   - `pyproject.toml`: name, version ALWAYS `1.0.3`, license, description, an open email (passinbox)
   - `README.md` with the same structure/icons, only adapt the content
   - `LICENSE`, `INSTALL.md`, `CONTRIBUTING.md`, `.github/ISSUE_TEMPLATE/config.yml`
4. Research the language
5. Research the prompt — perpetual until the user is fully satisfied

**Cycles:** no approval → keep iterating the same step, never move forward on your own.

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS

Moving a step forward without an explicit "yes" invalidates all subsequent work — you have to roll back.
