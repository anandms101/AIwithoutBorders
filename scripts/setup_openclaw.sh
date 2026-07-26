#!/usr/bin/env bash
# Configure OpenClaw as the Outpost agent harness, against local Ollama only.
#
# Reproduces the working configuration on a fresh box. Every setting here was
# arrived at by measurement, not guesswork:
#
#   baseUrl        local Ollama. Invariant 1 — no remote inference, ever.
#   auth profile   OpenClaw refuses to call a provider with no credential.
#                  Ollama ignores the value; it exists to satisfy OpenClaw.
#   maxTokens      THE latency fix. Uncapped output made one narration take
#                  67s. Capped to 400 it is ~1-5s. Alert rationales are three
#                  sentences; nothing needs more.
#   contextWindow  32768. The default 262144 loads gemma4:12b at 10GB and
#                  wrecks co-residency. Do NOT drop this to 8192 — OpenClaw's
#                  own system prompt exceeds it and every call then fails with
#                  "Context overflow: prompt too large".
set -euo pipefail

MODEL="${OUTPOST_AGENT_MODEL:-gemma4:12b}"
OLLAMA_URL="${OLLAMA_OPENAI_URL:-http://127.0.0.1:11434/v1}"

if ! command -v openclaw >/dev/null 2>&1; then
  echo "ERROR: openclaw not on PATH. Install with: npm install -g openclaw" >&2
  exit 1
fi

echo "==> OpenClaw $(openclaw --version 2>/dev/null || echo '?')"

echo "==> Pointing OpenClaw at local Ollama: $OLLAMA_URL"
openclaw config set models.providers.ollama.baseUrl "$OLLAMA_URL"

echo "==> Capping output tokens (latency) and context window (memory)"
openclaw config set models.providers.ollama.maxTokens 400
openclaw config set models.providers.ollama.contextWindow 32768

echo "==> Registering a placeholder credential (Ollama ignores it)"
if openclaw models auth list 2>/dev/null | grep -q "ollama"; then
  echo "    already present"
else
  printf 'ollama-local\n' | openclaw models auth paste-api-key --provider ollama
fi

echo "==> Setting default model: $MODEL"
openclaw models set "ollama/$MODEL"

echo "==> Verifying a real turn"
REPLY=$(openclaw --no-color agent --local --session-key outpost-setup-check \
  --message "Reply with exactly: OUTPOST-OK" 2>/dev/null | tail -20)

if echo "$REPLY" | grep -q "OUTPOST-OK"; then
  echo "    OK — agent turn succeeded against local Ollama"
else
  echo "ERROR: agent turn did not return the expected reply. Output was:" >&2
  echo "$REPLY" >&2
  exit 1
fi

echo "==> Done"
