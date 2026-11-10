# Product Requirements Document

> **Status**: Active | **Version**: 1.0.1 | **Date**: 2026-11-07

## Project Summary

Personal Agent Kit (PAK) is a brain and governance layer for coding agents. It runs on top of
Claude Code and OpenCode through hooks, plugins, MCP and SKILL.md, and adds what those engines
leave to the user: a memory that lasts between sessions, guards that stop dangerous actions, and
protocols that travel with the repo.

PAK has no agent loop of its own. An engine can change without losing what the user built on top
of it.

## Goals and Objectives

### Main Objectives

- **Remember:** keep useful context between sessions, on the user's machine.
- **Protect:** block dangerous actions with real controls, not with prose in a prompt.
- **Work unattended:** take a task from a queue to a reviewed patch, with a spending limit.

### Non-goals

- A desktop app, a terminal UI, a web app or an agent loop of its own.
- A multi-chat gateway, a kanban board or a skills marketplace.
- Routing across hundreds of models. The user chooses the provider.
- Multi-user or fleet operation. PAK is for one person on their own machine.

### Success Metrics

| Metric           | Target                                                    | Today                      |
| ---------------- | --------------------------------------------------------- | -------------------------- |
| Automated tests  | Green on every push                                       | Green locally; no CI run   |
| Coverage         | ≥ 96 % (enforced by `--cov-fail-under`)                   | 96.5 %                     |
| Clean install    | Works from a clone, in a clean container, without prompts | See `docs/install-test.md` |
| Guard corpus     | ≥ 50 cases that must block and ≥ 50 that must pass        | Not built                  |
| Memory benchmark | Reproducible, measured against a two-file baseline        | Not built                  |
| Comparison       | Any "better than X" claim has a reproducible report       | No such claim is made      |

## User

One developer using their own account on their own Linux machine. They may already run several
agents and want the same memory and the same guards in all of them.

PAK runs as that user and from wherever the repo was cloned. It never creates a Linux user.

## Functional Requirements

### FR-1: Installation

**Description**: One command installs the kit, on any user account and in any path.
**Priority**: High
**Status**: Shipped

**Acceptance Criteria**:

- [x] `bin/install.sh` runs without prompts with `--yes`, and prints its plan with `--dry-run`.
- [x] Optional parts are opt-in: BMAD, OpenCode, voice and development toolchains.
- [x] It creates no Linux user. Units and `.env` are rendered for the current user and path.
- [x] The core install runs no downloaded script.

### FR-2: Memory

**Description**: A local semantic memory that Claude Code and OpenCode share.
**Priority**: High
**Status**: Basic version shipped

**Acceptance Criteria**:

- [x] Local Qdrant and `memory_service`, with authentication required by default.
- [x] MCP access from both engines.
- [ ] Night consolidation and lessons tied to incidents.
- [ ] Injected once at session start, without depending on one engine's memory folder.
- [ ] Public benchmark with a baseline.

### FR-3: Governance

**Description**: Guards that run before an action, in both engines.
**Priority**: High
**Status**: Basic version shipped

**Acceptance Criteria**:

- [x] Write guard: secrets, credential files and syntax.
- [x] Recursive and forced `rm` guard.
- [ ] Two-stage guard for every command, with a human prompt when no judge is configured.
- [ ] Reversible quarantine instead of deletion.
- [ ] Injection scan on memory and context files.
- [ ] Corpus of cases that must block and cases that must pass, in both engines.

### FR-4: Autonomy

**Description**: A worker takes queued tasks to a reviewed patch.
**Priority**: Medium
**Status**: Planned

**Acceptance Criteria**:

- [ ] `pak` CLI with `doctor`, `setup`, `guard`, `memory`, `task`, `eval` and `import`.
- [ ] Work happens in a shadow workspace and ends in a patch, never in a commit.
- [ ] An independent judge reviews the patch, and its value is measured.
- [ ] A cost limit stops a task.

### FR-5: Agent team

**Description**: Personas and a way to create new ones.
**Priority**: Medium
**Status**: Shipped

**Acceptance Criteria**:

- [x] The kit's own personas are always available.
- [x] BMAD ships with the repo and activates on request.

### FR-6: Language

**Description**: One file decides the language of every surface.
**Priority**: Medium
**Status**: Shipped

**Acceptance Criteria**:

- [x] `ai18n.yaml` is injected into each Claude Code session, normalized by the resolver.
- [x] `--language` sets the reply and voice language at install time.
- [x] The same policy reaches OpenCode through its instructions.

## Non-Functional Requirements

### Performance

- A guard on a tool call must not be noticeable in normal use. Stage 1 is local and deterministic.

### Security

- Local by default: services listen on `127.0.0.1`.
- `memory_service` refuses to start without authentication.
- No secret lives in the repo. `.env` is created with mode 600.
- The Slack bot must be closed by default. This is planned; today an empty channel list allows
  every channel.

### Portability

- Ubuntu 24.04 is the tested target. Other distributions with `apt` and systemd should work.
- The repo must not depend on a specific user, home directory or clone path.

### Honesty

- Docs describe what exists. Planned work is marked as planned.
- Results are published with the command that reproduces them, including null results.

## Roadmap

| Phase | Scope                                                              | State   |
| ----- | ------------------------------------------------------------------ | ------- |
| 0     | Repository, languages, models, CI, docs, non-interactive installer | Done    |
| 1     | Full guard, quarantine, injection scan, closed Slack               | Planned |
| 2     | Memory v2, lessons, public benchmark                               | Planned |
| 3     | `pak` CLI, worker, shadow workspace, judge, cost limit             | Planned |
| 4     | Reproducible comparison against another harness                    | Planned |
