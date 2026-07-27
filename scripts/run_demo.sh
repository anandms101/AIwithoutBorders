#!/usr/bin/env bash
# Start the whole Outpost demo with one command, and tear it down cleanly.
#
#   ./scripts/run_demo.sh              # preflight, reset, start everything
#   ./scripts/run_demo.sh --no-reset   # keep existing state
#   ./scripts/run_demo.sh --stop       # stop everything
#   ./scripts/run_demo.sh --status     # what is running
#
# WHY A SUPERVISOR SCRIPT AND NOT DOCKER
#
# Ollama holds four models resident on the host GPU. Containerising Outpost
# would mean host networking plus GPU passthrough to reach it, which adds
# failure modes on demo day without removing any. The fragile part of this
# system is model residency, and that lives on the host either way. This script
# gives the thing Docker was wanted for -- one command, predictable ordering,
# health checks, clean teardown -- with nothing new to debug at 17:00.
set -uo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
LOG_DIR="${OUTPOST_LOG_DIR:-.run}"
WEB_PORT="${OUTPOST_WEB_PORT:-8081}"     # 8080 collides with the OpenShell gateway
RECEIVER_PORT="${OUTPOST_RECEIVER_PORT:-9000}"
OLLAMA_HOST_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"

RESET=1
MODE="start"

for arg in "$@"; do
  case "$arg" in
    --no-reset) RESET=0 ;;
    --stop)     MODE="stop" ;;
    --status)   MODE="status" ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

mkdir -p "$LOG_DIR"

# ---------------------------------------------------------------- helpers ---

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
dim()   { printf '\033[2m%s\033[0m\n' "$*"; }

stop_all() {
  local stopped=0
  for pidfile in "$LOG_DIR"/*.pid; do
    [ -e "$pidfile" ] || continue
    local pid name
    pid=$(cat "$pidfile" 2>/dev/null || true)
    name=$(basename "$pidfile" .pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && stopped=$((stopped + 1))
      echo "    stopped $name (pid $pid)"
    fi
    rm -f "$pidfile"
  done
  [ "$stopped" = "0" ] && echo "    nothing was running"
  return 0
}

show_status() {
  local any=0
  for pidfile in "$LOG_DIR"/*.pid; do
    [ -e "$pidfile" ] || continue
    local pid name
    pid=$(cat "$pidfile" 2>/dev/null || true)
    name=$(basename "$pidfile" .pid)
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      green "    running   $name (pid $pid)"
    else
      red   "    dead      $name"
    fi
    any=1
  done
  [ "$any" = "0" ] && echo "    nothing running"
  return 0
}

start_service() {
  local name="$1"; shift
  "$@" > "$LOG_DIR/$name.log" 2>&1 &
  echo $! > "$LOG_DIR/$name.pid"
  dim "    started $name (pid $(cat "$LOG_DIR/$name.pid")) -> $LOG_DIR/$name.log"
}

wait_for_http() {
  local url="$1" name="$2" tries="${3:-30}"
  for _ in $(seq 1 "$tries"); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      green "    ready     $name"
      return 0
    fi
    sleep 1
  done
  red "    FAILED    $name did not come up at $url"
  return 1
}

# ------------------------------------------------------------------ modes ---

case "$MODE" in
  stop)   echo "==> Stopping"; stop_all; exit 0 ;;
  status) echo "==> Status";   show_status; exit 0 ;;
esac

# -------------------------------------------------------------- preflight ---

echo "==> Preflight"
FAIL=0

if [ ! -x "$PY" ]; then
  red "    missing   $PY — run: uv venv --python 3.12 && uv pip install -r requirements-dev.txt"
  FAIL=1
else
  green "    ok        python venv"
fi

if curl -fsS --max-time 3 "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1; then
  green "    ok        ollama at $OLLAMA_HOST_URL"
else
  red   "    missing   ollama is not answering at $OLLAMA_HOST_URL"
  FAIL=1
fi

# Model residency is the fragile part, so check it explicitly rather than
# discovering a missing model mid-demo.
for model in medgemma embeddinggemma; do
  if curl -fsS --max-time 3 "$OLLAMA_HOST_URL/api/tags" 2>/dev/null | grep -q "$model"; then
    green "    ok        model $model"
  else
    red   "    missing   model $model — pull it before the demo"
    FAIL=1
  fi
done

if command -v openclaw >/dev/null 2>&1; then
  green "    ok        openclaw $(openclaw --version 2>/dev/null | head -1)"
else
  dim   "    absent    openclaw — alerts will use the deterministic rationale"
fi

# OpenClaw issues its own Ollama requests and does not set keep_alive, so a
# narration reloads the agent model on Ollama's default 5m timer and undoes the
# warm-up below. Only the server-wide default fixes that for every caller.
if systemctl show ollama --property=Environment 2>/dev/null | grep -q "OLLAMA_KEEP_ALIVE=-1"; then
  green "    ok        ollama keep-alive is server-wide"
else
  dim   "    note      OLLAMA_KEEP_ALIVE is not set server-wide."
  dim   "              Outpost pins its own calls, but OpenClaw's do not, so the"
  dim   "              agent model can drop off 'ollama ps' ~5m after a narration."
  dim   "              Run 'make keepalive' once (needs sudo) to make it stick."
fi

for port in "$WEB_PORT" "$RECEIVER_PORT"; do
  if ss -tln 2>/dev/null | grep -q ":$port "; then
    red "    in use    port $port is already bound"
    FAIL=1
  else
    green "    ok        port $port free"
  fi
done

if [ "$FAIL" != "0" ]; then
  echo ""
  red "Preflight failed. Fix the above and re-run."
  exit 1
fi

# --------------------------------------------------------------- warm models ---
#
# `ollama ps` is on-camera evidence for the co-residency claim, but a model is
# only listed once it has served a request. Without this the audience sees one
# or two models and the "four resident" claim looks false. A trivial prompt per
# model costs a few seconds and makes the claim visibly true.
#
# Whisper is not an Ollama model -- it runs under CTranslate2 in the worker
# process -- so it will never appear in `ollama ps`. Three here is correct.
echo ""
echo "==> Warming models (so 'ollama ps' shows them resident)"
for model in "${OUTPOST_VISION_MODEL:-medgemma:latest}" \
             "${OUTPOST_AGENT_MODEL:-gemma4:12b}"; do
  if curl -fsS --max-time 180 "$OLLAMA_HOST_URL/api/generate" \
       -d "{\"model\":\"$model\",\"prompt\":\"ok\",\"stream\":false,\"keep_alive\":-1,\"options\":{\"num_ctx\":4096,\"num_predict\":1}}" \
       >/dev/null 2>&1; then
    green "    warm      $model"
  else
    dim   "    skipped   $model (not pulled?)"
  fi
done

if curl -fsS --max-time 120 "$OLLAMA_HOST_URL/api/embed" \
     -d "{\"model\":\"${OUTPOST_EMBED_MODEL:-embeddinggemma:300m}\",\"input\":\"ok\",\"keep_alive\":-1}" \
     >/dev/null 2>&1; then
  green "    warm      ${OUTPOST_EMBED_MODEL:-embeddinggemma:300m}"
else
  dim   "    skipped   ${OUTPOST_EMBED_MODEL:-embeddinggemma:300m}"
fi

# ------------------------------------------------------------------ start ---

echo ""
echo "==> Clearing any previous run"
stop_all

if [ "$RESET" = "1" ]; then
  echo ""
  echo "==> Resetting demo state"
  ./scripts/reset_demo.sh 2>&1 | sed 's/^/    /'
fi

echo ""
echo "==> Starting services"
start_service receiver  "$PY" -m mock_receiver
start_service watcher   "$PY" -m outpost.watcher
start_service heartbeat "$PY" -m outpost.agent.heartbeat
start_service web       "$PY" -m uvicorn outpost.web.app:app \
                              --host 0.0.0.0 --port "$WEB_PORT" --log-level warning

echo ""
echo "==> Health checks"
wait_for_http "http://127.0.0.1:$RECEIVER_PORT/health" "receiver" || FAIL=1
wait_for_http "http://127.0.0.1:$WEB_PORT/api/status"  "web"      || FAIL=1

sleep 1
for name in watcher heartbeat; do
  pid=$(cat "$LOG_DIR/$name.pid" 2>/dev/null || true)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    green "    ready     $name"
  else
    red   "    FAILED    $name exited — see $LOG_DIR/$name.log"
    FAIL=1
  fi
done

if [ "$FAIL" != "0" ]; then
  echo ""
  red "Startup failed. Logs are in $LOG_DIR/."
  exit 1
fi

echo ""
green "==> Outpost is running"
echo ""
echo "    Dashboard : http://127.0.0.1:$WEB_PORT/"
echo "    Receiver  : http://127.0.0.1:$RECEIVER_PORT/reports"
echo "    Logs      : $LOG_DIR/"
echo ""
echo "    Drop the demo cases:  ./scripts/drop_demo_cases.sh --decoys"
echo "    Stop everything:      ./scripts/run_demo.sh --stop"
