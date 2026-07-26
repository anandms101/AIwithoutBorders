# Copilot instructions — FieldSignal

Project: **FieldSignal** — an always-on clinical triage and outbreak-surveillance agent for
disconnected field hospitals, running entirely on a Dell Pro Max with GB10. Hackathon build
(Dell x NVIDIA Local AI). No patient data leaves the box.

**`AGENTS.md` in the repository root is the canonical standing context — read it first.**
The full source of truth lives in `docs/`:

- `docs/ONE_PAGER.md` — pitch, problem, product, why-local, buyers, safety posture, rubric
- `docs/PRD.md` — goals/non-goals, user stories, architecture, F-IDs, NFRs, schedule, risks
- `docs/ARCHITECTURE.md` — component contracts, SQLite schema, agent tools, payload shapes
- `docs/BUILD_PLAN.md` — timeboxed milestones, gates, cut lines, ownership
- `docs/DEMO_RUNBOOK.md` — demo script, choreography, fallbacks, Q&A prep
- `docs/DECISIONS.md` — open questions and the decision log

## Hard invariants (do not violate, do not "improve")

1. **No remote inference in the agent runtime path.** All models run locally via Ollama /
   local serving inside the NemoClaw / OpenShell sandbox. Never add a hosted-model SDK,
   never call an external API, never download weights at runtime.
2. **Egress is one allowlisted host, aggregate counts only.** No names, ages, free text,
   or identifiers may ever be serialised into an outbound payload.
3. **Human gate before any transmission.** Approve/Dismiss in the UI, always.
4. **Triage and prioritise; never diagnose.** All outputs are drafts for a clinician.
5. **Alert logic reads structured fields only** (syndrome code, timestamp, catchment, film
   score) — never raw translated free text.
6. **Models stay resident**: `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_MAX_LOADED_MODELS >= 4`.
7. **Durable state**: SQLite on disk. Never in-memory-only.
8. **Log every agent tool call** with timestamp and arguments — that log is the trace panel.

## Do not build (explicit non-goals)

DICOM parsing · radiologist-grade reports · multilingual ASR beyond the demo language ·
per-language fine-tuning · EMR/DHIS2/OpenMRS integration · auth/multi-user/RBAC ·
deterioration monitoring · multi-site federation · mobile clients · SPA frameworks ·
Neo4j or any new stateful service.

## Stack (fixed)

Python 3.11+ · `watchdog` watcher on `/data/inbox` · SQLite for jobs, graph and vectors ·
Whisper large-v3 (ASR + translation) · MedGemma 4B via Ollama (vision) · small local
embedding model (case-definition RAG) · Nemotron 3 Super **quantized/smaller variant**
(agent reasoning) · OpenClaw harness under NemoClaw/OpenShell · FastAPI + server-rendered
HTML (no SPA, no build step) · HTTP POST to a single mock receiver for egress.

Model memory budget ≤ 70 GB total, ≥20% headroom in 128GB.

## Code conventions

- Python 3.11+, stdlib first; pin every dependency (venue Wi-Fi is unusable).
- Reference the functional-requirement ID in commits and PRs: `F-06: heartbeat …`.
- Structured JSON at every model boundary: prompt with a strict schema, parse, validate,
  and provide a deterministic fallback when output is unparseable.
- Config centralised (`config.py` / `.env.example`); no scattered literals or magic paths.
- Server-rendered Jinja templates; no client-side framework, no bundler.
- Never swallow exceptions on the demo path — surface them into the trace log.
- Boring and inspectable beats clever. A judge may read it; a teammate will debug it fast.

## Language rules for user-facing copy

Use "triage", "prioritise", "flag for review", "abnormality score", "review recommended".
Never "diagnose", "detect disease", "confirm", "rule out", or name a disease in an alert.
Alerts describe signal (`3 cases matching acute watery diarrhoea, sector-4, 72h`), never
conclusions. The goal is shorter time-to-investigation, not automated outbreak declaration.

## When the schedule bites

Priority order is `P0 (F-01…F-10)` → `P1 (F-11)` → `P2 (F-12)`. At each gate in
`docs/BUILD_PLAN.md`, take the stated cut line rather than extending scope. The non-goals
list is binding.
