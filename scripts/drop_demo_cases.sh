#!/usr/bin/env bash
# Drop the demo cases into the watched inbox.
#
# This is the one unscripted moment in the demo: files appear, nobody touches a
# keyboard, and the agent picks them up (G1).
#
#   ./scripts/drop_demo_cases.sh            # the 3 clustering cases
#   ./scripts/drop_demo_cases.sh --decoys   # add the 2 that must NOT fire
#   ./scripts/drop_demo_cases.sh --notes-only   # skip audio/films (fast path)
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
DATA_ROOT="${OUTPOST_DATA_ROOT:-./data}"
INBOX="${OUTPOST_INBOX:-$DATA_ROOT/inbox}"
CASES_DIR="demo_cases"
WITH_DECOYS=0
WITH_MEDIA=1

for arg in "$@"; do
  case "$arg" in
    --decoys)     WITH_DECOYS=1 ;;
    --notes-only) WITH_MEDIA=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

if [ ! -d "$CASES_DIR" ]; then
  echo "==> Generating demo cases"
  "$PY" scripts/make_demo_cases.py --outdir "$CASES_DIR" >/dev/null
fi

# Audio and films are what make the transcript and imaging panels show
# anything. Generated once and cached, so the venue's Wi-Fi is never involved.
if [ ! -f "$CASES_DIR/case-0421.wav" ] && [ "$WITH_MEDIA" = "1" ]; then
  echo "==> Generating demo media (audio + films)"
  "$PY" scripts/make_demo_media.py --outdir "$CASES_DIR" 2>/dev/null \
    | grep -vE "onnxruntime|^$" | sed 's/^/    /' || true
fi

mkdir -p "$INBOX" "$DATA_ROOT"

# The catchment manifest must be in place BEFORE the cases are processed,
# otherwise every case falls back to the site default and lands in one bucket.
cp "$CASES_DIR/catchments.tsv" "$DATA_ROOT/catchments.tsv"

CLUSTER=(case-0421 case-0422 case-0423)
DECOYS=(case-0424 case-0425)

# Drop every file belonging to a case: note, recording and film all share the
# filename stem, so the watcher groups them into one case (ARCHITECTURE §2).
drop_case() {
  local case_id="$1"
  local dropped=""
  for ext in txt wav jpg png; do
    if [ -f "$CASES_DIR/$case_id.$ext" ]; then
      if [ "$WITH_MEDIA" = "0" ] && [ "$ext" != "txt" ]; then continue; fi
      cp "$CASES_DIR/$case_id.$ext" "$INBOX/"
      dropped="$dropped $ext"
      sleep 0.3
    fi
  done
  echo "    $case_id ->$dropped"
}

echo "==> Dropping cluster cases into $INBOX"
for case_id in "${CLUSTER[@]}"; do
  drop_case "$case_id"
done

if [ "$WITH_DECOYS" = "1" ]; then
  echo "==> Dropping decoys (these must NOT trigger an alert)"
  for case_id in "${DECOYS[@]}"; do
    drop_case "$case_id"
  done
fi

echo "==> Done. Watch the trace panel."
