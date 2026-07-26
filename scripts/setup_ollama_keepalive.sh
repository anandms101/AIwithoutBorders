#!/usr/bin/env bash
# Enforce AGENTS.md invariant 6: models stay resident.
#
# Outpost also sends keep_alive=-1 on every request (outpost/llm.py), so the
# invariant holds without this script. But anything that talks to Ollama outside
# Outpost -- `ollama run`, OpenClaw, a teammate poking at the API -- will still
# evict models on the default 5m timer. Run this on the demo box.
#
# Requires sudo.
set -euo pipefail

DROPIN_DIR=/etc/systemd/system/ollama.service.d
DROPIN=$DROPIN_DIR/override.conf

echo "==> Writing $DROPIN"
sudo mkdir -p "$DROPIN_DIR"
sudo tee "$DROPIN" >/dev/null <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_MAX_LOADED_MODELS=4"
EOF

echo "==> Reloading systemd and restarting ollama"
sudo systemctl daemon-reload
sudo systemctl restart ollama

echo "==> Waiting for Ollama to come back"
for _ in $(seq 1 30); do
  if curl -fsS --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "    ready"
    break
  fi
  sleep 1
done

echo "==> Verify (UNTIL column should read 'Forever' once a model is loaded)"
ollama ps
