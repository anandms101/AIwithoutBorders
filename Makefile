# Outpost — one-command targets.
#
#   make setup     first-time install
#   make demo      preflight, reset, start everything
#   make drop      drop the demo cases into the inbox
#   make stop      stop everything
#   make test      the suite (no model calls)
#   make verify    the suite including live model calls

PY := .venv/bin/python
UV := uv

.DEFAULT_GOAL := help
.PHONY: help setup setup-asr demo drop stop status test test-live verify clean clean-all fmt

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the venv and install runtime + dev dependencies
	$(UV) venv --python 3.12
	$(UV) pip install -r requirements-dev.txt
	@echo "Done. Next: make setup-asr (large download), then make demo"

setup-asr: ## Install faster-whisper and fetch Whisper large-v3 (~3GB, needs internet)
	$(UV) pip install -r requirements-asr.txt
	./scripts/fetch_asr_model.sh

openclaw: ## Configure OpenClaw against local Ollama
	./scripts/setup_openclaw.sh

keepalive: ## Pin Ollama models resident (needs sudo)
	./scripts/setup_ollama_keepalive.sh

demo: ## Preflight, reset state, start all four services
	./scripts/run_demo.sh

demo-keep: ## Start services without resetting state
	./scripts/run_demo.sh --no-reset

drop: ## Drop the demo cases into the watched inbox
	./scripts/drop_demo_cases.sh --decoys

stop: ## Stop all services
	./scripts/run_demo.sh --stop

status: ## Show what is running
	./scripts/run_demo.sh --status

reset: ## Reset to clean pre-populated demo state
	./scripts/reset_demo.sh

test: ## Run the test suite (no model calls)
	$(PY) -m pytest tests/ -q -m "not live"

test-live: ## Run only the tests that hit real local models
	$(PY) -m pytest tests/ -q -m live

verify: ## Full suite including live model calls
	$(PY) -m pytest tests/ -q

clean: ## Remove generated state (keeps cached media and voice model)
	rm -rf data .run demo_cases
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

clean-all: ## Also remove cached films and the Piper voice (forces re-download)
	rm -rf data .run demo_cases demo_media .voices
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
