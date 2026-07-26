#!/usr/bin/env bash
# Drop the demo cases into the watched inbox.
#
# This is the one unscripted moment in the demo: files appear, nobody touches a
# keyboard, and the agent picks them up (G1).
#
#   ./scripts/drop_demo_cases.sh            # the 3 clustering cases
#   ./scripts/drop_demo_cases.sh --decoys   # add the 2 that must NOT fire
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
DATA_ROOT="${OUTPOST_DATA_ROOT:-./data}"
INBOX="${OUTPOST_INBOX:-$DATA_ROOT/inbox}"
CASES_DIR="demo_cases"
WITH_DECOYS=0

for arg in "$@"; do
  case "$arg" in
    --decoys) WITH_DECOYS=1 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$CASES_DIR" ]; then
  echo "==> Generating demo cases"
  "$PY" scripts/make_demo_cases.py --outdir "$CASES_DIR" >/dev/null
fi

mkdir -p "$INBOX" "$DATA_ROOT"

# The catchment manifest must be in place BEFORE the cases are processed,
# otherwise every case falls back to the site default and lands in one bucket.
cp "$CASES_DIR/catchments.tsv" "$DATA_ROOT/catchments.tsv"

CLUSTER=(case-0421 case-0422 case-0423)
DECOYS=(case-0424 case-0425)

echo "==> Dropping cluster cases into $INBOX"
for case_id in "${CLUSTER[@]}"; do
  cp "$CASES_DIR/$case_id.txt" "$INBOX/"
  echo "    $case_id.txt"
  sleep 0.4
done

if [ "$WITH_DECOYS" = "1" ]; then
  echo "==> Dropping decoys (these must NOT trigger an alert)"
  for case_id in "${DECOYS[@]}"; do
    cp "$CASES_DIR/$case_id.txt" "$INBOX/"
    echo "    $case_id.txt"
    sleep 0.4
  done
fi

echo "==> Done. Watch the trace panel."
