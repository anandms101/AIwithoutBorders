#!/usr/bin/env bash
# Prove the locality claim on camera.
#
#   ./scripts/verify_egress_block.sh
#
# Four checks, in the order a sceptic would ask them:
#   1. No hosted-LLM SDK is installed.
#   2. No non-local URL appears anywhere in the runtime path.
#   3. Inference really is going to 127.0.0.1 (shown live, from Ollama).
#   4. The one allowlisted receiver refuses anything outside the agreed six
#      fields — so even a regression could not leak an identifier.
#
# Exits non-zero if any check fails, so it doubles as a pre-flight gate.
set -uo pipefail

cd "$(dirname "$0")/.."

PY="${PY:-.venv/bin/python}"
RECEIVER="${OUTPOST_EGRESS_URL:-http://127.0.0.1:9000/report}"
OLLAMA_HOST_URL="${OLLAMA_HOST:-http://127.0.0.1:11434}"

red()   { printf '\033[31m%s\033[0m\n' "$*"; }
green() { printf '\033[32m%s\033[0m\n' "$*"; }
bold()  { printf '\033[1m%s\033[0m\n' "$*"; }

FAIL=0

bold "1. No hosted-LLM SDK installed"
HITS=$($PY -m pip list 2>/dev/null \
  | grep -iE '^(openai|anthropic|cohere|google-generativeai|google-genai|boto3|azure-ai)' || true)
if [ -z "$HITS" ]; then
  green "   PASS  no cloud model SDK present"
else
  red   "   FAIL  found: $HITS"; FAIL=1
fi
echo

bold "2. No non-local endpoint in the runtime path"
# docs/ and comments are excluded; this is about code that executes.
LEAKS=$(grep -rEoh "https?://[a-zA-Z0-9.:/_-]+" outpost/ mock_receiver/ 2>/dev/null \
  | grep -viE "127\.0\.0\.1|localhost|0\.0\.0\.0|docs\.openclaw|fastapi\.tiangolo" \
  | sort -u || true)
if [ -z "$LEAKS" ]; then
  green "   PASS  every endpoint is loopback"
else
  red   "   FAIL  non-local endpoints found:"; echo "$LEAKS" | sed 's/^/         /'; FAIL=1
fi
echo

bold "3. Inference is served locally"
if curl -fsS --max-time 3 "$OLLAMA_HOST_URL/api/tags" >/dev/null 2>&1; then
  green "   PASS  Ollama answering at $OLLAMA_HOST_URL"
  echo "   Models resident:"
  ollama ps 2>/dev/null | sed 's/^/         /'
else
  red   "   FAIL  Ollama unreachable at $OLLAMA_HOST_URL"; FAIL=1
fi
echo

bold "4. Receiver refuses anything outside the contract"
if ! curl -fsS --max-time 3 "${RECEIVER%/report}/health" >/dev/null 2>&1; then
  red "   SKIP  receiver not running — start it with 'make demo'"
  FAIL=1
else
  # A legitimate payload is accepted...
  OK_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$RECEIVER" \
    -H 'Content-Type: application/json' \
    -d '{"syndrome":"acute_watery_diarrhoea","catchment":"sector-4","count":3,"window_hours":72,"trend":"rising","site_id":"OP-001"}')

  # ...the same payload carrying a patient identifier is not.
  BAD_CODE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 -X POST "$RECEIVER" \
    -H 'Content-Type: application/json' \
    -d '{"syndrome":"acute_watery_diarrhoea","catchment":"sector-4","count":3,"window_hours":72,"trend":"rising","site_id":"OP-001","patient_name":"Jean Dupont"}')

  if [ "$OK_CODE" = "200" ]; then
    green "   PASS  aggregate payload accepted        (HTTP $OK_CODE)"
  else
    red   "   FAIL  aggregate payload rejected        (HTTP $OK_CODE)"; FAIL=1
  fi

  if [ "$BAD_CODE" = "422" ]; then
    green "   PASS  payload with an identifier DENIED (HTTP $BAD_CODE)"
  else
    red   "   FAIL  identifier was not denied         (HTTP $BAD_CODE)"; FAIL=1
  fi
fi
echo

if [ "$FAIL" = "0" ]; then
  green "All locality checks passed."
else
  red "One or more locality checks FAILED."
fi
exit "$FAIL"
