#!/usr/bin/env bash
# bin/measure-footprint.sh — FULL agent footprint, by layer.
# The agent isn't just persona+protocols: it's harness + resident + on-demand + all of bmad +
# knowledge (memory) + operational. Counted with tiktoken cl100k_base (real BPE; a Claude proxy).
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
REPO_ROOT="$(pwd)"

# Counted with a REAL tokenizer (tiktoken cl100k_base) via bin/count_tokens.py — no more bytes/4.
CT=".venv/bin/python bin/count_tokens.py"
t() { $CT file "$1"; }   # one file
tdir() { $CT dir "$1"; } # every file in the dir (recursive)
tmd() { $CT md "$1"; }   # *.md recursive
tmd1() { $CT md1 "$1"; } # *.md top-level only
KG="$HOME/.claude/projects/${REPO_ROOT//\//-}/memory"
row() { printf '  %-44s %s\n' "$1" "$2"; }
tk() { printf '  %-44s ~%7d tok\n' "$1" "$2"; }

printf '═══════ FULL agent footprint (≈ tokens) ═══════\n\n'

printf 'LAYER 1 — HARNESS (Claude Code CLI, outside the repo):\n'
row "base system prompt + built-in tool defs" "~10-20k (estimate, CLI)"
row "MCP servers (CLAUDE_MCP_CONFIG: context7…)" "variable (estimate, CLI)"

printf '\nLAYER 2 — RESIDENT (always; bot pipeline --add-dir + session-start):\n'
tk "roster (manifest)" "$(t .bmad/_cfg/agent-manifest.csv)"
tk "AGENTS.md (--add-dir)" "$(t AGENTS.md)"

printf '\nLAYER 3 — ON-DEMAND (per task):\n'
tk "enforcement (read first)" "$(t protocols/PROTOCOL-ENFORCEMENT-ABSOLUTE.md)"
tk "full protocols" "$(tmd1 protocols)"
tk "compact protocols (LIGHT)" "$(tmd protocols/compact)"
tk "ultra protocols (enforcement, NOT light)" "$(tmd protocols/ultra)"
tk "README.md" "$(t README.md)"
tk "bmad commands (when invoked)" "$(tmd .bmad/integrations/claude/commands)"

printf '\nLAYER 4 — BMAD FRAMEWORK:\n'
tk ".bmad/bmm/agents (USED: party-mode team)" "$(tdir .bmad/bmm/agents)"
tk ".bmad/bmm REST (workflows/testarch/dev: not used day-to-day)" "$(($(tdir .bmad/bmm) - $(tdir .bmad/bmm/agents)))"
for d in core bmb cis _cfg local; do tk ".bmad/$d" "$(tdir .bmad/$d)"; done
tk "→ .bmad TOTAL on disk" "$(tdir .bmad)"
row "  (at runtime: roster ~4k, or one activated agent ~1.2k)" ""

printf '\nLAYER 5 — KNOWLEDGE (RAG/recall):\n'
tk "memory KG (.md, $(find "$KG" -name '*.md' 2>/dev/null | wc -l) files)" "$(tmd "$KG")"
row "agent_memory (Qdrant)" "variable (RAG per query)"

printf '\nLAYER 6 — OPERATIONAL: pull/push (hook dance + pipeline), tool outputs, conversation — these grow.\n'

printf '\n── Summary ──\n'
RES=$(($(t .bmad/_cfg/agent-manifest.csv) + $(t AGENTS.md) + $(t "$KG/MEMORY.md")))
BMM_DEAD=$(($(tdir .bmad/bmm) - $(tdir .bmad/bmm/agents)))
UNIVERSE=$(($(tdir .bmad) + $(tmd "$KG") + $(tmd protocols)))
tk "RESIDENT per task (always loaded)" "$RES"
tk "Relevant UNIVERSE (excluding the rest of bmm that never loads)" "$((UNIVERSE - BMM_DEAD))"
tk "Total on disk (incl. dead bmm that never loads)" "$UNIVERSE"
printf '  (real runtime ≈ resident + protocols + whatever the task activates; the rest of bmm never loads)\n'
