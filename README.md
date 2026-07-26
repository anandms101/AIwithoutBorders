# Outpost

**Always-on clinical triage and outbreak surveillance for disconnected field hospitals —
running entirely on the Dell Pro Max with GB10.**

A clinician dictates a consultation, uploads an X-ray, writes a note. Everything lands in a
watched folder on the box. Outpost runs continuously and unprompted: translates, scores
the film, maps the presentation onto a WHO syndromic case definition, links the patient
into a longitudinal graph, watches for clusters across days, and escalates to a human when
a threshold trips.

**No patient data leaves the box.** The only thing that crosses the wire — after a human
approves it — is an aggregate count: *"eleven cases of acute watery diarrhoea, sector 4,
past 72 hours, rising."* Never a record.

> It triages and prioritises. **It never diagnoses.** Every output is a draft for a
> clinician, and every escalation path has a human gate.

Hackathon build for Dell x NVIDIA Local AI.

---

## Quickstart

Requires Python 3.12+, [`uv`](https://docs.astral.sh/uv/), and a running
[Ollama](https://ollama.com). Everything else is local.

```bash
# 1. Install
make setup                       # venv + runtime and dev dependencies

# 2. Pull the models (once, needs internet — the venue has none)
ollama pull medgemma
ollama pull embeddinggemma:300m
ollama pull gemma4:12b

# 3. Run everything
make demo                        # preflight, reset state, start all four services

# 4. In another terminal — the unscripted moment
make drop                        # copies the demo cases into the watched inbox
```

Then open **<http://127.0.0.1:8081/>**.

> **Presenting this?** [`DEMO_GUIDE.md`](DEMO_GUIDE.md) has the exact commands, what to say
> at each panel, how to show OpenClaw, and what to do if something breaks on stage.

```bash
make stop                        # stop everything
make status                      # what's running
make test                        # 235 tests, no model calls
```

`make demo` preflights before it starts anything: venv present, Ollama answering, each
required model pulled, and both ports free. It fails with a specific message rather than
starting half a system.

### What you should see

Within ~30 seconds of `make drop`:

| Where | What |
| --- | --- |
| **Inbox panel** | 5 cases appear — nobody touched a keyboard. Each tagged `audio` / `film` / `note` |
| **Agent trace** | `enqueue_file` → `transcribe` → `score_film` → `map_presentation` → `write_case` → `query_graph` → `raise_alert`, live |
| **Alerts** | Exactly **one**: *3 cases matching acute watery diarrhoea, sector-4, 72h, rising* |
| **Case detail** | French audio player, side-by-side transcript + translation, and the chest film with its score |
| **Egress preview** | The exact payload and its size — **124 bytes** — shown *before* you approve |
| **Byte counters** | ~3.9 MB on box vs 124 sent once approved — a **31,000:1** ratio |

Multimodal cases take ~90–120s to process (Whisper on CPU). Add `--notes-only` for a
sub-2-second run: `./scripts/drop_demo_cases.sh --decoys --notes-only`.

Two of the five cases are **decoys that must not fire**: same syndrome in a different
catchment, and a different syndrome in the same catchment. Both are processed and mapped
correctly, and neither contributes to the alert. That is the evidence the threshold is
real rather than a hardcoded trigger.

Press **Approve** and the aggregate lands at
<http://127.0.0.1:9000/reports>. Press **Dismiss** and nothing is transmitted at all.

### Optional

```bash
make setup-asr    # faster-whisper + Whisper large-v3 weights (~3GB, needs internet)
make openclaw     # point OpenClaw at local Ollama (agent narration)
make keepalive    # pin models resident via systemd (needs sudo)
```

Without these the system still runs: alerts use a deterministic rationale instead of an
agent-written one, and audio cases fail loudly rather than silently.

### Configuration

Everything is environment-driven — see [`.env.example`](.env.example). The two you are
most likely to change:

```bash
OUTPOST_WEB_PORT=8081                            # 8080 collides with the OpenShell gateway
OUTPOST_EGRESS_URL=http://<laptop>:9000/report   # the single allowlisted host
```

---

## Documentation

Start with **[`AGENTS.md`](AGENTS.md)** — the standing context for every contributor and
every AI agent working in this repo.

| Doc | Contents |
| --- | --- |
| [`docs/ARC.md`](docs/ARC.md) | **What is actually built** — status per requirement, how each part degrades, measured numbers, divergences, invariant enforcement, prepared Q&A |
| [`docs/ONE_PAGER.md`](docs/ONE_PAGER.md) | The pitch: problem, product, why it can't run in the cloud, who pays, safety posture, rubric alignment, sources |
| [`docs/PRD.md`](docs/PRD.md) | Technical execution PRD: goals/non-goals, user stories, architecture, functional requirements, NFRs, demo data, schedule, risks |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Repo layout, SQLite schema, agent tool signatures, model-boundary schemas, egress contract, config |
| [`docs/DATASETS.md`](docs/DATASETS.md) | Dataset selection and why, exact licence clauses, rejected alternatives, USB manifest, attribution strings |
| [`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md) | Timeboxed milestones, gates, cut lines, workstream ownership, risk register |
| [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) | 5-minute demo script, choreography, pre-flight checklist, Q&A prep, failure handling |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Open questions, decision log, third-party clearance tracking |

The original source document (one-pager + PRD as delivered) is kept verbatim at
[`docs/AI Without Borders.pdf`](docs/AI%20Without%20Borders.pdf). The markdown docs above
are the working copies — edit those, not the PDF.

## Architecture at a glance

```
data/inbox/ ──watcher──▶ jobs (SQLite) ──▶ pipeline workers
                                │
        ┌───────────────────────┼────────────────┬────────────────┐
        ▼                       ▼                ▼                ▼
  ASR/translate          vision scorer     case-def RAG     graph writer
        └───────────────────────┴────────────────┴────────────────┘
                                │
                  artifacts — free text lives here, and stops here
                                │
                  only STRUCTURED fields cross into the graph
                                │
                      heartbeat loop (every 30s)
                                │
              tools: query_graph, get_case_def,
                     score_film, raise_alert
                                │
               alert ──▶ UI review ──▶ human approve
                                │
              egress (one allowlisted host, counts only, 124 bytes)
```

The separation in the middle is the important part. Cluster detection reads a denormalised
`cases` table that has **no column capable of holding narrative text**, so a hallucinated
clause is structurally incapable of manufacturing an outbreak — not merely discouraged
from it.

## Stack

All inference is local. There are no remote LLM or API calls in the agent's runtime path.

| Layer | Choice |
| --- | --- |
| Hardware | Dell Pro Max with GB10 — Grace Blackwell, 128GB unified memory, DGX OS |
| Agent harness | **OpenClaw**, driven locally against Ollama |
| ASR + translation | Whisper large-v3 via CTranslate2 (`faster-whisper`) |
| Medical vision | `medgemma` via Ollama |
| Case-definition RAG | `embeddinggemma:300m` + SQLite vector table |
| Agent reasoning | `gemma4:12b` — see note below |
| Storage | SQLite on disk (WAL) — jobs, graph, vectors, trace, alerts |
| UI | FastAPI + server-rendered Jinja, no SPA, no build step |

> **Substitution:** the PRD specifies Nemotron 3 Super for agent reasoning. It is not
> available on this box, so `gemma4:12b` is used — the only model verified end-to-end
> through OpenClaw. This and three other divergences are documented with the measurements
> that forced them in [`docs/ARC.md`](docs/ARC.md) §6.

Models stay resident (`keep_alive=-1` on every request). Current footprint is ~13.6GB of a
≤70GB budget, leaving ample headroom so the background heartbeat and foreground clinician
work don't contend.

**Context length, not parameter count, drives residency.** `ollama ps` showed
`phi4-mini:3.8b` holding 20GB purely from a 131k default context. `num_ctx` is pinned per
role; without that, co-residency fails for a reason unrelated to model size.

## Attribution

Chest X-ray imagery comes from **TBX11K** (Nankai University) and the **COVID-19
Radiography Database** (Qatar University), both CC BY 4.0, with **NIH ChestX-ray14** for
testing volume. Syndromic case definitions are paraphrased into our own schema from the WHO
2023 EWAR operational guide (WHO/UXH/EPR/2023.1, CC BY-NC-SA 3.0 IGO) and carry WHO's
required adaptation disclaimer — this project is not created, endorsed or reviewed by WHO.
Consultation audio is self-recorded in French; all synthetic case data is self-authored.

Full licence analysis, the rejected alternatives and copy-ready citation strings are in
[`docs/DATASETS.md`](docs/DATASETS.md); clearance status is tracked in
[`docs/DECISIONS.md`](docs/DECISIONS.md) §Third-party content.

## Licence

See [`LICENSE`](LICENSE).
