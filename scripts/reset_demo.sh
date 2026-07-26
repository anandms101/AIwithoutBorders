#!/usr/bin/env bash
# Reset to a clean, pre-populated demo state.
#
# Must be idempotent and complete in under 60s (ARCHITECTURE §9). You will run
# this more than once, and at least once under time pressure.
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
DATA_ROOT="${OUTPOST_DATA_ROOT:-./data}"
START=$(date +%s)

echo "==> Clearing state"
rm -rf "$DATA_ROOT"
mkdir -p "$DATA_ROOT/inbox" "$DATA_ROOT/artifacts"

echo "==> Creating schema"
"$PY" -m outpost.db

echo "==> Seeding WHO case definitions"
if ! "$PY" scripts/seed_case_definitions.py >/dev/null 2>&1; then
  echo "    WARNING: embedding seed failed (Ollama down?)."
  echo "    F-04 will fall back to the keyword map — the demo still runs."
fi

echo "==> Seeding synthetic background graph"
"$PY" scripts/seed_background_graph.py | sed 's/^/    /'

echo "==> Generating demo case files"
"$PY" scripts/make_demo_cases.py --outdir demo_cases | sed 's/^/    /'

ELAPSED=$(( $(date +%s) - START ))
echo ""
echo "==> Reset complete in ${ELAPSED}s"

if [ "$ELAPSED" -ge 60 ]; then
  echo "    WARNING: exceeded the 60s budget in ARCHITECTURE §9"
  exit 1
fi

echo ""
echo "    Next:"
echo "      1. $PY -m outpost.watcher            # terminal 1"
echo "      2. $PY -m outpost.agent.heartbeat    # terminal 2"
echo "      3. $PY -m mock_receiver              # terminal 3 (off-box)"
echo "      4. uvicorn outpost.web.app:app --port 8080   # terminal 4"
echo "      5. ./scripts/drop_demo_cases.sh      # the unscripted moment"
