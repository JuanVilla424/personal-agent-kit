#!/usr/bin/env bash
# bin/benchmark-models.sh — model benchmark for the agent (latency + score per model).
# Runs ONE representative task per model, times it, judges the output with claude
# (the judge), and builds the table for MODELS.md §3. Robust: unreachable model → "n/a". Caches in temp/.
# Claude family via `claude --model`; the rest via `opencode run --model`.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
OUT="temp/benchmark"
mkdir -p "$OUT"
CALL_TIMEOUT="${BENCH_TIMEOUT:-75}"
JUDGE_MODEL="${BENCH_JUDGE:-opus}"
PY="$PWD/.venv/bin/python"

# zai's (GLM) key lives in ~/.bashrc; non-interactive shells don't load it (early-return).
# We load it if missing — so GLM runs without having to invoke via `bash -ic`. Never prints the value.
if [ -z "${ZAI_API_KEY:-}" ] && [ -f "$HOME/.bashrc" ]; then
    eval "$(grep -hE '^[[:space:]]*export[[:space:]]+ZAI_API_KEY=' "$HOME/.bashrc" 2>/dev/null | head -1)" 2>/dev/null || true
fi

SYS="You are a technical assistant. Respond in ENGLISH, concisely, redacting IDs and credentials, and showing a summary before proposing any action."
TASK="A production server averages 4% CPU usage over the last 7 days. What do you recommend and why? Redact any ID."

# cli|model_id|label
MODELS=(
    "claude|claude-opus-5-5|Opus 5.5"
    "claude|claude-sonnet-5-5|Sonnet 5.5"
    "claude|claude-haiku-5-5|Haiku 5.5"
    "claude|claude-fable-5-1|Fable 5.1"
    "opencode|zai/glm-5.2|GLM-5.2"
    "opencode|opencode/deepseek-v4-flash-free|DeepSeek-v4-flash"
    "opencode|opencode/nemotron-3-ultra-free|Nemotron-3-ultra"
    "opencode|opencode/mimo-v2.5-free|MiMo-v2.5"
    "opencode|opencode/north-mini-code-free|North-mini-code"
    "opencode|opencode/big-pickle|Big-pickle"
    "opencode|custom/standard|Standard"
    "opencode|custom/extended|Extended"
)

strip_ansi() { "$PY" -c "import sys,re; sys.stdout.write(re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]','',sys.stdin.read()))"; }
safe_name() { echo "$1" | tr ' /.' '___'; }

echo "=== Phase 1: running models (timeout ${CALL_TIMEOUT}s each) ==="
for entry in "${MODELS[@]}"; do
    cli="${entry%%|*}"
    rest="${entry#*|}"
    mid="${rest%%|*}"
    label="${rest#*|}"
    safe="$(safe_name "$label")"
    [ -s "$OUT/$safe.out" ] && {
        echo "  $label: (cache)"
        continue
    }
    printf '  %-20s ... ' "$label"
    t0=$(date +%s)
    if [ "$cli" = "claude" ]; then
        timeout "$CALL_TIMEOUT" claude -p --model "$mid" --append-system-prompt "$SYS" "$TASK" >"$OUT/$safe.out" 2>/dev/null || true
    else
        timeout "$CALL_TIMEOUT" opencode run --model "$mid" "${SYS}"$'\n\n'"${TASK}" 2>/dev/null | strip_ansi >"$OUT/$safe.out" || true
    fi
    t1=$(date +%s)
    echo $((t1 - t0)) >"$OUT/$safe.lat"
    if [ -s "$OUT/$safe.out" ]; then echo "ok ($((t1 - t0))s)"; else
        echo "N/A" >"$OUT/$safe.out"
        echo "n/a"
    fi
done

echo ""
echo "=== Phase 2: judge (${JUDGE_MODEL}) ==="
RUBRIC="Evaluate a model's RESPONSE. Given task: '${TASK}'. Rubric (0-10): technical correctness (a production server at 4% CPU = oversized → recommend a downsize and/or generation upgrade, never shutting PROD down), natural English quality, ID redaction, and conciseness. Return ONLY a number 0-10."
for entry in "${MODELS[@]}"; do
    label="${entry##*|}"
    safe="$(safe_name "$label")"
    [ -s "$OUT/$safe.score" ] && continue
    body="$(cat "$OUT/$safe.out")"
    if [ "$body" = "N/A" ]; then
        echo "n/a" >"$OUT/$safe.score"
        continue
    fi
    printf '  %-20s ... ' "$label"
    score="$(timeout 60 claude -p --model "$JUDGE_MODEL" "${RUBRIC}"$'\n\nRESPONSE:\n'"${body}" 2>/dev/null | grep -oE '([0-9]|10)(\.[0-9])?' | head -1)"
    echo "${score:-?}" >"$OUT/$safe.score"
    echo "score=${score:-?}"
done

echo ""
echo "=== Table (for MODELS.md §3) ==="
printf '| %-18s | %-8s | %-9s | %-7s |\n' "Model" "latency" "out(tok≈)" "score/10"
printf '| %-18s | %-8s | %-9s | %-7s |\n' "------------------" "--------" "---------" "-------"
for entry in "${MODELS[@]}"; do
    label="${entry##*|}"
    safe="$(safe_name "$label")"
    lat="$(cat "$OUT/$safe.lat" 2>/dev/null || echo '?')"
    score="$(cat "$OUT/$safe.score" 2>/dev/null || echo '?')"
    body="$(cat "$OUT/$safe.out" 2>/dev/null || echo '')"
    if [ "$body" = "N/A" ]; then
        otok="n/a"
        lat="n/a"
    else otok=$(.venv/bin/python bin/count_tokens.py file "$OUT/$safe.out"); fi
    printf '| %-18s | %-8s | %-9s | %-7s |\n' "$label" "${lat}s" "$otok" "$score"
done
