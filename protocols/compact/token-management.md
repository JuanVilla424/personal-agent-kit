# Token Management Protocol (Compact)

**Version**: 1.0.1

## Token Zones

| Zone        | Range     | Status  | Action            |
| ----------- | --------- | ------- | ----------------- |
| 🟢 GREEN    | 0-120k    | Safe    | Normal operation  |
| 🟡 YELLOW   | 120k-150k | Caution | Monitor closely   |
| 🔴 RED      | 150k-170k | Warning | Limit operations  |
| 🚨 CRITICAL | 170k+     | Danger  | Immediate compact |

## Pre-Flight Checks

**MANDATORY before large operations:**

Token check required before:

- Reading multiple large files
- Creating comprehensive documents
- Running extensive analysis
- Multi-file searches

**If in YELLOW ZONE or higher:**

- Confirm necessity with user
- Consider deferring to next session
- Suggest compact if needed

## Current Usage

Always report at session start and before large operations.

## Compact When

- User requests: "/compact" or "pre-compact"
- Approaching CRITICAL ZONE (>165k)
- Before starting major new task in RED ZONE

## Violations = Task Halt

Ignoring token limits causes immediate task halt.
