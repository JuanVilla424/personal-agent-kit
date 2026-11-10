---
name: fastapi-project-service
description: Use when adding or changing an endpoint in one of this project's FastAPI services (local/scripts/memory_index/memory_service.py). Keeps the same Settings/auth/test-fixture conventions the service already uses.
allowed-tools: [Read, Edit, Write, Bash, Grep, Glob]
---

# FastAPI service in this project's style

This package has one reference FastAPI service:
`local/scripts/memory_index/memory_service.py` (+ `config.py`). Before touching this service,
or creating a new one alongside it, **read the real `config.py`/`memory_service.py`** — this
summarizes the pattern, it doesn't replace them.

## Rules

1. **Settings = `@dataclass` with `.from_env()`.** Every config value comes from
   `os.getenv(...)`, never hardcoded. See `Settings.from_env()` in `config.py` as the
   exact template for fields/style.

2. **Token auth, identity ALWAYS verified.** The pattern is `_resolve()` in
   `memory_service.py`: identity comes from the TOKEN, never from a field the client sends
   (anti-IDOR). **Fail-closed**: if no auth is configured, the service does NOT start — never
   an "open mode" by default.

3. **Routes inline in `create_app()`/at module level.** The `@app.get`/`@app.post` handlers are
   defined right next to the app's construction, not in a separate `APIRouter`. That's how the
   existing routes are — follow the same style, don't introduce a new pattern.

4. **Tests use the `make_settings` fixture.** `tests/conftest.py` exposes
   `make_settings(tmp_path, **overrides) -> Settings` + `settings`/`client` fixtures
   (`TestClient(create_app(settings))`). A new test uses those fixtures or calls
   `make_settings(tmp_path, field=value)` directly if it needs a different config — never
   touches the real `.env`, never hardcodes paths outside `tmp_path`.

5. **Run the full suite before finishing** — `.venv/bin/pytest tests/ -q --no-cov`.
   The repo already defines this in its own `pyproject.toml`.

## When adding a new endpoint

1. Read the real `config.py` to see which settings already exist (don't duplicate one that's
   already there).
2. Add the route, following the style of the neighboring routes (auth via the token's
   verified identity, error handling via `HTTPException`).
3. New test in `tests/test_<name>.py`, using `make_settings`/`client` from `conftest.py`.
4. Run the full suite, not just the new file.
