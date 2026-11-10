# 📦 Versioning Strategy

We follow [Semantic Versioning](https://semver.org/) with the version format `MAJOR.MINOR.PATCH`.

## 🧩 Version Components

- **MAJOR:** Increments when you make incompatible API changes.
- **MINOR:** Increments when you add functionality in a backward-compatible manner.
- **PATCH:** Increments when you make backward-compatible bug fixes.

Starting version is `1.0.1` (never `0.x.x`, never `1.0.0`) — see the
[Semantic Versioning Protocol](protocols/semantic-versioning.md) for the full rule set.

## 🌿 Branch Workflow

Personal repo, single maintainer — no staged rollout pipeline:

1. **dev:** active work happens here.
2. **main:** stable branch. `dev` merges into `main` via pull request when ready.

## 📝 Commit Message Guidelines

Each commit message should include one of the [commit types](#-commit-types) below and an
optional scope. To flag a version bump, add one of the [versioning keywords](#-versioning-keywords).

### 🗂️ Commit Message Structure

```bash
<type>(<scope>): <description> [versioning keyword]
```

Example:

```bash
feat(core): add oauth2 support [minor candidate]
```

### 🔤 Commit Types

- **feat**: a new feature for the user.
- **fix**: a bug fix for the user.
- **docs**: documentation only changes.
- **style**: changes that do not affect the meaning of the code (white-space, formatting, etc.).
- **refactor**: a code change that neither fixes a bug nor adds a feature.
- **perf**: a code change that improves performance.
- **test**: adding missing tests or correcting existing tests.
- **chore**: changes to the build process or auxiliary tools and libraries.

### 🔑 Versioning Keywords

Optional — include one at the end of the commit message to flag the bump type:

- **[major candidate]** — this commit should trigger a MAJOR version bump.
- **[minor candidate]** — this commit should trigger a MINOR version bump.
- **[patch candidate]** — this commit should trigger a PATCH version bump.

## 🚀 How a Version Bump Actually Happens

There's no CI pipeline promoting branches or bumping versions automatically. Per the
[Version Approval Protocol](protocols/version-approval.md): the assistant may propose a bump
and classify its type, but never triggers one on its own initiative — only the user's own
commit, carrying the marker above, starts the real mechanism:

1. `bump2version` reads `current_version` from `.bumpversion.cfg` — the single source of
   truth, syncing `pyproject.toml`, `README.md`, and `.bmadrc.yaml` together.
2. It's never invoked directly by the assistant; a preview is safe to run any time and
   changes nothing: `.venv/bin/bumpversion --dry-run --list --allow-dirty [patch|minor|major]`.
3. `CHANGELOG.md` is updated by hand — it's not auto-generated from commits.

## ⭐ Best Practices

- **Atomic Commits**: ensure each commit represents a single logical change.
- **Descriptive Messages**: write clear and concise commit messages that accurately describe the changes.
- **Consistent Format**: adhere strictly to the commit message structure above.
- **Avoid Force Pushes**: respect branch protection rules to maintain repository integrity.

---

## 📜 License

2026 — This is private, proprietary software. All rights reserved. See the [LICENSE](LICENSE) file included in this repository.
