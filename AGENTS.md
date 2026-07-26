# AGENTS.md — Outpost

> **Read this first, every session.** This file is the standing context for every AI agent
> and every human working in this repository. If something here conflicts with a request,
> say so before acting.

## What we are building

**Outpost** — an always-on clinical triage and outbreak-surveillance agent for
disconnected field hospitals, running **entirely on a Dell Pro Max with GB10** (Grace
Blackwell, 128GB coherent unified memory, DGX OS / Ubuntu 24.04 base).

One line: *An always-on clinical agent for disconnected field hospitals that turns every
consultation into outbreak surveillance, with no patient data leaving the box.*

This is a **hackathon build** (Dell x NVIDIA Local AI). It is optimised for a 5-minute
live demo and a 3-minute recorded video, not for production longevity. Judge every
decision against the rubric in `docs/ONE_PAGER.md` §Rubric alignment.

The product is named **Outpost** (locked — `docs/DECISIONS.md` D10). Use it verbatim in
UI strings, the deck, and the video. Package/module namespace is `outpost`; environment
variables are prefixed `OUTPOST_`.

## Current state — update this section when it changes

> **Keep this honest.** It is the first thing a new session reads to avoid assuming code
> exists. Update it in the same commit as the work it describes.

- **Docs:** complete. One-pager, PRD, architecture contracts, build plan, demo runbook and
  decision log are all in `docs/`.
- **Code:** **none yet.** No `outpost/` package, no `scripts/`, no `mock_receiver/`.
  The layout in `docs/ARCHITECTURE.md` §1 is the *target*, not the current tree.
- **Box:** not provisioned in this repo's context. NemoClaw onboarding, model loading and
  the egress allowlist are Infra tasks tracked in `docs/BUILD_PLAN.md`.
- **Blocking:** open questions Q2, Q4, Q5 in `docs/DECISIONS.md` are unresolved. Q2
  (Nemotron variant) gates real work — flag it rather than guessing. Q1 (demo language) is
  resolved: **French** (D11). Q3 (product name) is resolved: **Outpost** (D10).
- **Data:** datasets are chosen, licence-cleared and documented in `docs/DATASETS.md`.
  **Nothing is downloaded yet** and no fetch tooling exists.

## Commands

No build, test or lint tooling exists yet. **Do not invent commands** — if you add
tooling, record the verified command here.

| Task | Command |
| --- | --- |
| Watcher + workers | _not yet implemented_ — target: `python -m outpost.watcher` |
| Agent heartbeat | _not yet implemented_ — target: `python -m outpost.agent.heartbeat` |
| Web UI | _not yet implemented_ — target: `uvicorn outpost.web.app:app --host 0.0.0.0 --port 8080` |
| Tests | _none yet_ |
| Verify models resident | `ollama ps` (on the box) |

## Canonical documents

| Doc | What it is | When to read it |
| --- | --- | --- |
| `docs/ONE_PAGER.md` | The pitch: problem, product, why-local, who pays, safety posture | Before any narrative, README, or demo work |
| `docs/PRD.md` | Technical execution PRD: goals, non-goals, architecture, F-IDs, NFRs | Before any code change |
| `docs/ARCHITECTURE.md` | Component contracts, data model, tool signatures, payload shapes | Before touching a component boundary |
| `docs/DATASETS.md` | Dataset selection, exact licence clauses, rejected alternatives, USB manifest, attribution | Before touching demo data, the case-definition table, or anything that appears in the video |
| `docs/BUILD_PLAN.md` | Timeboxed schedule, gates, cut lines, workstream ownership | At every gate; when deciding what to drop |
| `docs/DEMO_RUNBOOK.md` | 5-minute demo script, choreography, fallbacks, Q&A prep | Before changing anything on the demo path |
| `docs/DECISIONS.md` | Open questions + decision log | When an open question blocks you; record the answer here |

The original delivered document is preserved verbatim at `docs/AI Without Borders.pdf`.
The markdown files are the working copies — never edit the PDF.

## Non-negotiable invariants

These are architectural, not stylistic. Breaking one breaks the pitch.

1. **No remote inference. Ever.** No LLM/API call may exist in the agent's runtime path.
   All inference is local (Ollama / local serving) inside the NemoClaw / OpenShell
   sandbox. If you are about to add an SDK that calls a hosted model, stop.
2. **No patient data leaves the box.** The only thing that may cross the wire is an
   approved aggregate payload: counts only, no names, no ages, no free text, no
   identifiers. See `docs/ARCHITECTURE.md` §6 Egress contract.
3. **Human gate on every escalation path.** Nothing is transmitted without an explicit
   Approve action in the UI.
4. **It triages and prioritises. It never diagnoses.** Every model output is a *draft for
   a clinician*. No output text may be phrased as a diagnosis.
5. **Alerts fire on structured fields only** — syndrome code, timestamp, catchment, film
   score. **Never on raw translated free text.** A hallucinated clause must not be able
   to manufacture an outbreak.
6. **Models stay resident.** `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_MAX_LOADED_MODELS >= 4`.
   Model swapping between heartbeat cycles kills the always-on claim.
7. **State is durable on disk.** SQLite files, never in-memory-only. A crash 20 minutes
   before the pitch must not lose the pre-populated graph.
8. **Every agent tool call is logged with timestamp + arguments.** That log *is* the
   trace panel — 30% of the score depends on visible reasoning.

## Explicit non-goals — do not build these

Named deliberately. This is discipline, not incompleteness. If asked to add one of
these, push back and cite this list.

- DICOM parsing (use PNG/JPEG)
- Radiologist-grade report generation
- More than one ASR source language
- Per-language fine-tuning on-box
- EMR / DHIS2 / OpenMRS integration
- Authentication, multi-user, RBAC
- Deterioration monitoring for admitted patients
- Multi-site federation
- Any mobile client
- Any SPA framework (server-rendered HTML only)
- Neo4j or any new stateful service (the graph is SQLite tables)

## Tech stack (fixed — do not substitute)

| Layer | Choice |
| --- | --- |
| Watcher | Python `watchdog` (inotify) on `/data/inbox` |
| Job store + graph + vectors | SQLite (on disk) |
| ASR + translation | Whisper large-v3, local serving |
| Medical vision | MedGemma 4B via Ollama |
| Case-definition RAG | Small local embedding model + SQLite vector table |
| Agent reasoning | Nemotron 3 Super — **quantized / smaller variant**, not the 120B |
| Agent harness | OpenClaw under NemoClaw / OpenShell |
| UI | FastAPI + server-rendered HTML (Jinja), no SPA, no build step |
| Egress | HTTP POST to exactly one allowlisted mock receiver |

Model memory budget must total **≤ 70 GB**, leaving ≥20% headroom in 128GB. Verify with
`ollama ps` after load.

## Working conventions

- **Python 3.11+**, standard library first. Add a dependency only when it removes real
  work. Pin versions — the venue has no usable Wi-Fi.
- **No network access at build time.** Models and datasets load from the USB/external
  drive. Never write code that downloads weights at runtime.
- Every functional requirement has an ID (`F-01` … `F-12`). Reference the ID in commit
  messages and PR titles: `F-06: heartbeat queries graph every 30s`.
- Prefer boring, inspectable code. A judge may read it; a teammate will debug it under
  time pressure.
- Config lives in one place (`config.py` / `.env.example`), never scattered literals.
- Structured JSON for every model boundary. Parse, validate, and have a deterministic
  fallback for unparseable model output.
- Do not silently swallow exceptions on the demo path — log them into the trace.

## Priority order when time is short

`P0 (F-01…F-10)` → `P1 (F-11)` → `P2 (F-12)`. When a gate in `docs/BUILD_PLAN.md`
fires, take the cut line. Do not negotiate with the schedule.

## Safety language rules

When writing any user-facing string, alert text, or README copy:

- Say "triage", "prioritise", "flag for review", "abnormality score". Never "diagnose",
  "detect disease", "confirm", "rule out".
- Alerts describe *signal*, not conclusions: "3 cases matching acute watery diarrhoea in
  sector-4 within 72h — review recommended", never "cholera outbreak".
- Goal is **shorter time-to-investigation**, not automated outbreak declaration.
- Thresholds are calibrated per setting — say so wherever thresholds are surfaced.

## Attribution / clearance

All third-party content must be cleared and cited in the writeup: X-ray datasets (TBX11K,
COVID-19 Radiography Database, NIH ChestX-ray14), speech corpora, model weights, and WHO
case definitions (paraphrased into our own schema, with WHO's required adaptation
disclaimer). Full licence analysis is in `docs/DATASETS.md`; clearance status is tracked in
`docs/DECISIONS.md` §Third-party content.

**Before anything goes on camera**, check `docs/DATASETS.md` §7. Some assets are
non-commercial and must never appear in the recorded video.
