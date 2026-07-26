# Outpost — Technical Execution PRD

**Version:** 1.0 · Hackathon build · Dell x NVIDIA Local AI on Dell Pro Max with GB10
**Timebox:** Demo video + project submission by 18:30. Pitch deck by 19:00. Code freeze at
video submission.
**Team:** 3–4 builders, roster locked at kickoff.

---

## 1. Product overview

**One-line:** An always-on clinical agent for disconnected field hospitals that turns every
consultation into outbreak surveillance, with no patient data leaving the box.

**Problem:** WHO's EWARN outbreak-surveillance workflow in humanitarian settings still runs
on paper forms and manual threshold counting. Separately, specialist reads (radiology
especially) take days. The clinical signal exists at the point of care; nobody can act on
it fast enough.

**Primary user:** A clinical officer at a district-level field hospital — not a radiologist,
not an epidemiologist, running 40+ consultations a day, with intermittent connectivity and
no specialist on site.

**Secondary user:** The project medical lead, who approves what escalates off-site.

**Why this hardware:** Four models must stay resident simultaneously for the heartbeat to
be continuous. That is a memory-capacity requirement that 128GB unified memory satisfies
and a 24GB consumer GPU does not.

---

## 2. Goals & non-goals

### Goals

| # | Goal | Demo-verifiable success criterion |
| --- | --- | --- |
| **G1** | Agent acts without being prompted | Files dropped in watched folder are processed with zero keyboard input |
| **G2** | Multimodal pipeline runs fully local | `nvidia-smi` / model list shows 4 resident models; egress policy blocks all non-allowlisted hosts |
| **G3** | Cluster detection across time | Alert fires on Nth case matching a syndromic definition within a window, against pre-populated background |
| **G4** | Human-gated, minimal egress | Approve action emits a JSON payload under 1KB containing counts only, no identifiers |
| **G5** | Visible agent reasoning | Trace panel shows tool calls in sequence during processing |

### Non-goals (explicit — do not build today)

- DICOM parsing. Use PNG/JPEG.
- Radiologist-grade report generation.
- More than one ASR source language.
- Per-language fine-tuning.
- EMR / DHIS2 / OpenMRS integration.
- Authentication, multi-user, RBAC.
- Deterioration monitoring for admitted patients.
- Multi-site federation.
- Any mobile client.

---

## 3. User stories

### P0 — must have, these are the demo

- As a clinical officer, I want my dictated consultation transcribed and translated to
  English so a colleague or the system can act on it.
- As a clinical officer, I want an uploaded chest X-ray scored automatically so I know
  which films need escalation first.
- As a clinical officer, I want to be told when my recent patients form a cluster, so I
  don't have to notice it myself across a week of notes.
- As a project medical lead, I want to review the agent's reasoning and approve before
  anything is transmitted.

### P1 — should have, build only if P0 is green by 15:00

- As a clinical officer, I want to see the original audio, the native transcript and the
  English translation side by side so I can verify the translation.
- As a project medical lead, I want to see exactly how many bytes left the box.

### P2 — nice to have, likely cut

- Returning-patient resolution across name-spelling variants.
- Overnight backlog batch summary.

---

## 4. System architecture

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

### Component responsibilities

| Component | Responsibility | Tech |
| --- | --- | --- |
| **Watcher** | Detect new files in `/data/inbox`, enqueue jobs | Python `watchdog` (inotify) |
| **Job store** | Durable queue + processed artifacts | SQLite |
| **ASR worker** | Speech → English translation, one pass | Whisper large-v3 via local serving |
| **Vision worker** | Chest film → abnormality score + findings | MedGemma (4B variant) via Ollama |
| **Case-def RAG** | Retrieve matching WHO syndromic case definition | Local embedding model + SQLite vector table |
| **Graph** | Patient / visit / syndrome nodes and edges | SQLite (nodes + edges tables). **Not** Neo4j — no time for a new service. |
| **Agent** | Heartbeat loop, tool calls, cluster reasoning, alert drafting | OpenClaw harness under NemoClaw / OpenShell |
| **UI** | Inbox view, trace panel, alert review, approve, byte counter | FastAPI + server-rendered HTML, no SPA |
| **Egress** | Emit approved aggregate payload to the single allowlisted endpoint | HTTP POST to a mock receiver on a second machine |

See `ARCHITECTURE.md` for schemas, tool signatures and payload contracts.

---

## 5. Devbox specification and setup

**Hardware:** Dell Pro Max with GB10 — Grace Blackwell, 128GB coherent unified memory,
Gen4 NVMe, DGX OS (Ubuntu 24.04 base). One box per team, plus monitor and
keyboard/mouse. Team codes on personal laptops; **the demo must run on the box**.

**Required stack per Rule 02:** NemoClaw, OpenClaw, or OpenShell. All inference local. No
remote LLM/API calls in the agent's runtime path.

### Setup sequence (owner: Infra, target complete by 11:30)

1. Verify Docker 28+ and the NVIDIA container runtime are present.
2. `nemoclaw onboard` — provisions the OpenShell sandbox, configures inference routing,
   applies filesystem and network policy from first boot.
3. Configure Ollama to serve on all interfaces via systemd drop-in.
4. **Load models from the USB/external drive.** Do not download at the venue — Wi-Fi will
   not support it.
5. Preload and pin weights so cold-start latency doesn't dominate the heartbeat.
6. Set the egress allowlist to exactly one host (the mock receiver). Verify a
   non-allowlisted request is denied.

### Model memory budget

Sum must leave ≥20% headroom in 128GB so the heartbeat and foreground work don't contend.
Verify actual resident sizes with `ollama ps` after load and adjust before committing.

| Role | Model | Budget |
| --- | --- | --- |
| Agent reasoning | Nemotron 3 Super — **quantized or smaller variant** | ~30–50 GB |
| Medical vision | MedGemma 4B | ~9 GB |
| ASR + translation | Whisper large-v3 | ~10 GB |
| Embeddings | Small local embedding model | ~1 GB |
| **Total target** | | **≤ 70 GB** |

**Decision:** the full 87GB Nemotron 3 Super 120B is the flashy choice and the wrong one.
It starves the other three models, kills co-residency, and co-residency *is* the pitch. Use
the quantized/smaller variant. If asked in Q&A: *"the box can run the 120B — but the
product needs four models hot at once, and that's the better use of the memory."*

### Critical config

- **Model keep-alive must be infinite.** If models unload between heartbeat cycles, load
  time dominates and the "always-on" claim collapses. Set `OLLAMA_KEEP_ALIVE=-1` and raise
  `OLLAMA_MAX_LOADED_MODELS` to at least 4.
- **Prove the egress policy on camera.** The OpenShell default-deny architecture
  (allowlisted endpoints, sandboxed writes) is your evidence for Rule 02 and for the "no
  cloud calls" criterion. Have a terminal ready showing a blocked outbound request.

---

## 6. Functional requirements

| ID | Requirement | Priority | Owner |
| --- | --- | --- | --- |
| **F-01** | Watcher detects new file in `/data/inbox` and enqueues within 2s | Must | Infra |
| **F-02** | Audio file → English translation, persisted with native transcript | Must | ML-A |
| **F-03** | Image file → abnormality score (0–100) + short findings text | Must | ML-B |
| **F-04** | Extracted presentation mapped to a WHO syndromic case definition | Must | ML-B |
| **F-05** | Case written to graph as patient/visit/syndrome nodes with timestamp and catchment | Must | Backend |
| **F-06** | Heartbeat runs every 30s, queries graph, evaluates thresholds | Must | Agent |
| **F-07** | Agent raises alert with linked case IDs and natural-language rationale | Must | Agent |
| **F-08** | UI shows live trace of agent tool calls in sequence | Must | Frontend |
| **F-09** | UI alert review with Approve / Dismiss | Must | Frontend |
| **F-10** | Approve emits allowlisted POST with aggregate counts only; byte size displayed | Must | Backend |
| **F-11** | UI shows audio + native transcript + English side by side | Should | Frontend |
| **F-12** | Returning-patient resolution across name variants | Nice | Backend |

### F-07 detail: alert logic

- **Trigger:** ≥3 cases matching the same syndromic case definition, same catchment,
  within a rolling 72h window.
- **Input to the agent:** structured fields only — syndrome code, timestamp, catchment,
  film score. **Never raw translated free text.** A hallucinated clause must not be able to
  manufacture an outbreak.
- **Agent output:** `{severity, syndrome, case_ids[], window, rationale_text}`.
- **Edge cases:** fewer than 3 cases → no alert. Cases spread across catchments → no alert
  (demonstrate this if time allows; it shows the thresholds are real). Duplicate file
  dropped twice → dedupe on content hash.

### F-10 detail: egress payload

```json
{"syndrome":"acute_watery_diarrhoea","catchment":"sector-4","count":11,"window_hours":72,"trend":"rising","site_id":"OP-001"}
```

No names, no ages, no free text, no identifiers. Display `bytes_sent` in the UI next to
`bytes_on_box`.

---

## 7. Non-functional requirements

| Area | Requirement |
| --- | --- |
| **Latency** | Single case end-to-end < 45s. Heartbeat cycle < 10s when no new cases. |
| **Concurrency** | Background heartbeat must not block foreground UI. Demonstrate both running simultaneously. |
| **Locality** | Zero non-allowlisted network calls during the entire demo. Enforced by OpenShell policy, not by convention. |
| **Durability** | State survives process restart — SQLite on disk, not in-memory. A crash 20 minutes before the pitch must not lose the pre-populated graph. |
| **Auditability** | Every agent tool call logged with timestamp and arguments. This log *is* the trace panel. |
| **Reliability** | Demo path must be idempotent and re-runnable in under 60s. You will run it more than once. |

---

## 8. Demo data requirements

| Asset | Source | Rule 06 note |
| --- | --- | --- |
| Chest X-rays | **TBX11K** + **COVID-19 Radiography Database** (both CC BY 4.0); NIH ChestX-ray14 for test volume. **Load from drive.** | Cleared — see `DATASETS.md`. VinDr-CXR/MIMIC-CXR were rejected (DICOM / credentialing) |
| Consultation audio | **Record yourselves in French** (D11) | Self-authored, no clearance issue |
| Background graph | Synthetic — 2 weeks of ordinary consultations, scripted | Self-authored |
| Cluster cases | Synthetic — 3 cases designed to trip the threshold | Self-authored |
| Case definitions | WHO syndromic definitions, paraphrased into your own schema | Cite source |

Pre-populating the background graph is not cheating — it's realistic, and it means cluster
detection runs against real noise instead of firing on an empty table.

---

## 9. Build schedule

See `BUILD_PLAN.md` for the working copy with gates and ownership.

| Time | Milestone | Cut line |
| --- | --- | --- |
| **now → 11:30** | Box provisioned, NemoClaw onboarded, 4 models loaded and pinned, egress policy verified | If models aren't hot by 11:30, drop to 3 models and cut the embedding/RAG step |
| **11:30 → 13:30** | Watcher + SQLite + graph schema + one worker end-to-end on a single file | — |
| **13:30 → 15:00** | All three workers wired; agent tool definitions; heartbeat loop firing | **15:00 gate:** if a case doesn't flow end-to-end, cut F-04 and hardcode syndrome mapping |
| **15:00 → 16:30** | UI: inbox, trace panel, alert review, approve, byte counter | **16:00 gate:** if trace panel isn't rendering, print tool calls to a terminal and screen-capture that instead — do not lose the trace |
| **16:30 → 17:15** | Pre-populate background graph. Full dry run, twice. Fix what breaks. | — |
| **17:15 → 18:00** | **Record the demo video.** Everything working, tight cuts. | Non-negotiable — start recording at 17:15 even if P1 items are unfinished |
| **18:00 → 18:30** | Writeup, GitHub URL, submit via BuilderBase | Submit at 18:15, not 18:29 |
| **18:30 → 19:00** | Pitch deck | — |

### Workstream ownership (4 builders)

- **Infra:** box setup, NemoClaw/OpenShell, model loading, egress policy, deployment
- **ML-A:** ASR + translation worker
- **ML-B:** vision scorer + case-definition mapping
- **Backend/Agent:** graph schema, heartbeat, agent tools, alert logic
- **Frontend** (shared, whoever finishes first): UI and trace panel

If 3 builders: Infra absorbs Frontend, and ML-A takes case-definition mapping.

---

## 10. Risks

| Risk | Severity | Mitigation |
| --- | --- | --- |
| Models not on drive; venue Wi-Fi can't download them | **Fatal** | Verify drive contents *before* touching anything else |
| Model swapping kills heartbeat continuity | High | `KEEP_ALIVE=-1`, verify with `ollama ps` under load |
| ASR output is garbage in chosen language | High | Demo in **French** (D11 — Arabic dialects hit 37.8–84.7% WER). Test with real recorded audio by 13:00, not 17:00 |
| Vision model produces prose, not a score | Medium | Constrain output with a strict JSON schema prompt; parse and validate; fall back to a fixed score if unparseable |
| Trace panel eats the whole afternoon | Medium | It's 30% of the score — protect it. Terminal output is an acceptable fallback |
| Live demo dies on stage | Medium | Recorded video cued on second monitor. Practice the handoff line |
| Scope creep back to five features | High | Non-goals list in §2 is binding. Re-read it at every gate |

---

## 11. Open questions to resolve by 11:30

Tracked in `DECISIONS.md`.

1. ~~Demo language — French or Arabic?~~ **Resolved: French** (D11 — Whisper is ~5–6% WER on
   French vs 37.8–84.7% on Arabic dialects).
2. Final Nemotron variant and actual resident size after quantization.
3. ~~Product name.~~ **Resolved: Outpost.**
4. Where does the mock egress receiver live — a teammate's laptop on the venue network, or
   a second local port? (Laptop is more convincing on camera.)
5. Who reads the pitch? Decide now; that person should not be debugging at 17:00.

---

## 12. Submission checklist

- [ ] **What have you built** — writeup covering value to companies, and **declare your
      stack** per Rule 06
- [ ] **Demo video file** — max 3 min, uploaded
- [ ] **Demo video URL** — optional
- [ ] **GitHub URL** — required
- [ ] Confirm all third-party content (X-ray datasets, models) is cleared and cited
- [ ] Confirm the demo runs on the box with no remote API calls in the runtime path
