---
name: pre-compact
description: Updates temp/current-context.md. THAT FILE ONLY. MAX 100 LINES.
allowed-tools: [Read, Edit]
---

# Pre-Compact: Update Context

## ABSOLUTE RULES

🚨 **ONLY update `temp/current-context.md`**
🚨 **MAX 100 lines**
🚨 **NO snapshots, NO recovery files, NO logs, NOTHING ELSE**

## Process

1. Read `temp/current-context.md`
2. Update with current state (max 100 lines)
3. Done — THE END

## Format (MAX 100 LINES TOTAL)

```markdown
# Current Context

**Updated**: {date time}
**Tokens**: {current}/200k ({%}%) - {zone}
**Version**: {version}

## Working On
{1-2 lines: what you're doing RIGHT NOW}

## Last Task
{1 line: last thing completed}

## Next Step
{1-2 lines: next action}

## Key Decisions
- {decision 1}
- {decision 2}
- {decision 3}

## Critical Files Touched
- {file 1}
- {file 2}

## State Variables
```yaml
task: {task}
version: {version}
status: {status}
party_mode: {true/false}
```

## Last 3 Messages
1. {msg}
2. {msg}
3. {msg}
```

**Keep EVERYTHING ultra-compact. Remove anything unnecessary.**
