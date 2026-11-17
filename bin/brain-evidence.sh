#!/usr/bin/env bash
# brain-evidence.sh — refreshes what the brain page's Health panel reads, so nothing there shows
# "missing" or "stale": a brain backup (~/.pak/backups/brain), the memory benchmark
# (temp/memory-benchmark/result.json) and the test coverage report (coverage.xml).
# The installer runs it once and agent-brain-evidence.timer runs it every week, inside the
# panel's freshness windows (backup 7 days, reports 8 days). Each step runs even when the one
# before it failed; the exit code is 1 when any of them failed.
set -uo pipefail
cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." || exit 1
PY=".venv/bin/python3"
rc=0

echo "== brain backup"
bin/pak brain backup || rc=1

echo "== memory benchmark (local, no model is called)"
bin/pak eval memory || rc=1

echo "== test suite with coverage (writes coverage.xml)"
# the notify tests read PDFs with pypdf. Only that line of notify's requirements goes into the
# root venv: the memory_service runs from this venv on memory_index's pinned fastapi, which the
# rest of notify's set would replace. pip returns at once when it is already there.
pypdf_req="$(grep -E '^pypdf' local/scripts/notify/requirements.txt)"
"$PY" -m pip install -q "${pypdf_req:-pypdf}" || rc=1
# coverage.xml is written even when a test or the coverage gate fails, and the panel reads it
# either way; a failing run is still reported through the exit code.
"$PY" -m pytest -q -p no:cacheprovider --no-header || rc=1
[ -f coverage.xml ] || rc=1

exit "$rc"
