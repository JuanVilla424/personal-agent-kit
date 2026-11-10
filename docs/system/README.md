# System Documentation

This directory contains permanent documentation about the BMAD system configuration and internal operations.

## Hooks

The real, currently-registered hook system lives in `local/hooks/` (versioned in this repo,
idempotently applied to `~/.claude/settings.json` by `local/hooks/install-hooks.py`) —
see **`local/hooks/README.md`** for the full table of hooks, what each one does, and how
registration works. This directory used to carry a separate, now-retired hook doc describing an
older `.ai/team-fullstack.txt`-based auto-continue system; that system and its documentation
were removed once confirmed unregistered and superseded by party-mode + the current hooks.

---

**Last Updated**: 2026-09-06
**Version**: 1.0.1
