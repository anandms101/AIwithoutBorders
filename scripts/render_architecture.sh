#!/usr/bin/env bash
# Re-render docs/architecture.png from docs/architecture.svg.
#
# The README embeds the PNG, so that is the one a judge actually sees. When the
# SVG is edited — the footer carries the test count and memory figures — the PNG
# goes stale silently, which is how it ended up claiming 235 tests when there
# were 272.
#
#   ./scripts/render_architecture.sh
#
# Output matches the original export dimensions (3000x1250).
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
SVG=docs/architecture.svg
PNG=docs/architecture.png

if [ ! -f "$SVG" ]; then
  echo "ERROR: $SVG not found" >&2
  exit 1
fi

if ! "$PY" -c "import cairosvg" 2>/dev/null; then
  echo "==> Installing cairosvg"
  uv pip install cairosvg
fi

echo "==> Rendering $SVG -> $PNG"
"$PY" - <<'PY'
import cairosvg

cairosvg.svg2png(
    url="docs/architecture.svg",
    write_to="docs/architecture.png",
    output_width=3000,
    output_height=1250,
)
PY

echo "==> Done"
ls -lh "$PNG"

# Cheap guard: the footer figure should match the suite. Not a hard failure,
# because the SVG is hand-edited and may legitimately be ahead or behind.
if command -v grep >/dev/null && [ -d tests ]; then
  CLAIMED=$(grep -oE '[0-9]+ unit tests' "$SVG" | grep -oE '^[0-9]+' || true)
  ACTUAL=$("$PY" -m pytest tests/ -q -m "not live" 2>/dev/null | grep -oE '^[0-9]+ passed' | grep -oE '^[0-9]+' || true)
  if [ -n "$CLAIMED" ] && [ -n "$ACTUAL" ] && [ "$CLAIMED" != "$ACTUAL" ]; then
    echo ""
    echo "    NOTE: diagram claims $CLAIMED unit tests, suite reports $ACTUAL."
    echo "    Update the footer in $SVG and re-run."
  fi
fi
