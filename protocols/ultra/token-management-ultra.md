# 🪙 Token Management Protocol (Ultra)

**Version**: 1.0.1
**Status**: NON-NEGOTIABLE ENFORCEMENT

---

## 🚫 Prohibitions

❌ NEVER read multiple large files without checking token zone first.
❌ NEVER start a major multi-file task in RED or CRITICAL zone.
❌ NEVER ignore a YELLOW+ warning and proceed at full scope.

---

## ✅ Rules

**Token zones:**

| Zone        | Range       | Action                                       |
| ----------- | ----------- | -------------------------------------------- |
| 🟢 GREEN    | 0 – 120k    | Normal operation                             |
| 🟡 YELLOW   | 120k – 150k | Monitor · confirm necessity before large ops |
| 🔴 RED      | 150k – 170k | Limit scope · defer non-critical reads       |
| 🚨 CRITICAL | 170k+       | `/compact` immediately before continuing     |

**Pre-flight check — required before:**

- Reading multiple large files
- Creating comprehensive documents
- Running extensive multi-file searches
- Any operation estimated > 5k tokens output

**If YELLOW or above:**

1. Confirm the operation is necessary now
2. Consider deferring to next session
3. Use `/compact` to compress context if at RED+

**Compact triggers:**

- User types `/compact` or `pre-compact`
- Approaching CRITICAL (> 165k)
- Before a major task while in RED zone

---

## ⚡ Enforcement

**On Violation:** HALT → REPORT → REQUIRE FIX → NO EXCEPTIONS
