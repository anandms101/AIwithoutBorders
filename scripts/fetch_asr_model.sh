#!/usr/bin/env bash
# Fetch Whisper large-v3 weights for F-02.
#
# Do this while you still have internet. The venue does not (BUILD_PLAN fatal
# risk: "models not on drive; venue Wi-Fi can't download them").
#
# Weights land in the HuggingFace cache and are reused offline thereafter.
set -euo pipefail

MODEL="${OUTPOST_ASR_MODEL:-large-v3}"
VENV="${VENV:-.venv}"

if [ ! -x "$VENV/bin/python" ]; then
  echo "ERROR: $VENV/bin/python not found. Create the venv first:" >&2
  echo "  uv venv --python 3.12 && uv pip install -r requirements-asr.txt" >&2
  exit 1
fi

echo "==> Fetching faster-whisper weights: $MODEL"
"$VENV/bin/python" - "$MODEL" <<'PY'
import sys
import time

from faster_whisper import WhisperModel

model_size = sys.argv[1]
started = time.perf_counter()

# Downloads to the HF cache on first use, then loads from disk forever after.
WhisperModel(model_size, device="cpu", compute_type="int8")

print(f"OK: {model_size} ready in {time.perf_counter() - started:.1f}s")
PY

echo "==> Cache location"
du -sh ~/.cache/huggingface 2>/dev/null || echo "  (cache dir not found)"
