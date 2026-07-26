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

## Documentation

Start with **[`AGENTS.md`](AGENTS.md)** — the standing context for every contributor and
every AI agent working in this repo.

| Doc | Contents |
| --- | --- |
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
/data/inbox/ ──watcher──▶ jobs (SQLite) ──▶ pipeline workers
                                │
        ┌───────────────────────┼────────────────┬────────────────┐
        ▼                       ▼                ▼                ▼
  ASR/translate          vision scorer     case-def RAG     graph writer
        └───────────────────────┴────────────────┴────────────────┘
                                │
                      heartbeat loop (agent)
                                │
              tools: query_graph, get_case_def,
                     score_film, raise_alert
                                │
               alert ──▶ UI review ──▶ approve
                                │
              egress (allowlisted, counts only)
```

## Stack

All inference is local. There are no remote LLM or API calls in the agent's runtime path.

| Layer | Choice |
| --- | --- |
| Hardware | Dell Pro Max with GB10 — Grace Blackwell, 128GB unified memory, DGX OS |
| Sandbox / harness | NemoClaw / OpenShell, OpenClaw agent harness — default-deny egress, sandboxed writes |
| ASR + translation | Whisper large-v3 |
| Medical vision | MedGemma 4B via Ollama |
| Case-definition RAG | Local embedding model + SQLite vector table |
| Agent reasoning | Nemotron 3 Super (quantized / smaller variant) |
| Storage | SQLite on disk — jobs, graph, vectors, trace, alerts |
| UI | FastAPI + server-rendered HTML |

Four models stay resident simultaneously (`OLLAMA_KEEP_ALIVE=-1`), total ≤70GB, leaving
≥20% headroom so the background heartbeat and foreground clinician work don't contend.

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
