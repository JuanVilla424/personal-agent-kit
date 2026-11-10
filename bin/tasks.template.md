# Tasks

TodoWrite substitute: this session doesn't have that tool available (cloud/background
surfaces don't ship it). Claude keeps the three lists below up to date by hand while
working. The `local/hooks/post-plan-approval.sh` hook (`PostToolUse` on `ExitPlanMode`,
registered via `local/hooks/install-hooks.py`) automatically dumps the just-approved plan
into "History" every time a plan is approved — Claude then turns it into a checklist in
the sections above.

"In progress"/"Completed" also serve as the log of open A2A delegations
(`protocols/a2a-protocol.md`): each `[A2A → <Agent>]` request the party-mode orchestrator
detects gets logged here as `[A2A <correlation_id>] <intent> · <emitter> →
<receiver> · hop:N/3 · pending`, moves to "Completed" with the verdict, or gets marked
`canceled` — this is what the `list-tasks`/`cancel-task` intents read and mutate.

## In progress

- (none)

## Pending

- (none)

## Completed

- (none)

## History of approved plans

<!-- post-plan-approval.sh appends entries here automatically. Do not edit by hand. -->
