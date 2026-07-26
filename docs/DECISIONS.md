# Decisions & Open Questions

Two sections: **open questions** that block work, and a **decision log** that records what
was chosen and why. Update this file the moment a question is answered — an unanswered
question here means someone is guessing.

---

## Open questions — resolve by 11:30

| # | Question | Why it blocks | Owner | Status |
| --- | --- | --- | --- | --- |
| Q1 | ~~**Demo language — French or Arabic?**~~ | — | ML-A | ✅ **Resolved → D11 (French)** |
| Q2 | ~~**Final Nemotron variant and actual resident size after quantization**~~ | — | Infra | ✅ **Resolved → D15** (`gemma4:12b`; Nemotron not on the box) |
| Q3 | ~~**Product name**~~ | — | Presenter | ✅ **Resolved → D10** |
| Q4 | **Where does the mock egress receiver live** — a teammate's laptop on the venue network, or a second local port? (Laptop is more convincing on camera.) | Sets the allowlist entry and `OUTPOST_EGRESS_URL` | Infra | ⬜ Open |
| Q5 | **Who reads the pitch?** Decide now; that person should not be debugging at 17:00. | Rehearsal time | All | ⬜ Open |

---

## Decision log

Decisions already made in the PRD — do not relitigate without a reason that fits in the
timebox.

| # | Decision | Rationale |
| --- | --- | --- |
| D1 | **Quantized / smaller Nemotron 3 Super**, not the full 87GB 120B | The 120B starves the other three models and kills co-residency — and co-residency *is* the pitch |
| D2 | **SQLite for the graph**, not Neo4j | No time to stand up a new service; nodes + edges tables are enough |
| D3 | **PNG/JPEG, not DICOM** | DICOM parsing is a non-goal; it buys nothing on stage |
| D4 | **FastAPI + server-rendered HTML**, no SPA | No build step, no bundler, no framework debugging at 16:00 |
| D5 | **Alert logic reads structured fields only** | A hallucinated clause must not be able to manufacture an outbreak |
| D6 | **Pre-populate the background graph** with 2 weeks of synthetic consultations | Not cheating — cluster detection must run against real noise, not an empty table |
| D7 | **One allowlisted egress host**, counts only, <1KB | Privacy is structural; it is also the demo's most memorable number |
| D8 | **Trace panel is protected scope** | Visible reasoning is 30% of the score; terminal output is the acceptable fallback |
| D9 | **Record the video before the deadline pressure**, ~17:15 | It's the artifact that survives if the live demo dies |
| D10 | **Product name is Outpost** (resolves Q3) | A field hospital *is* an outpost — forward-deployed, disconnected, self-sufficient. Survives being heard once over bad venue AV, no medical overclaim, and no collision with a well-known dev tool. Rejected: *Signal*, *Ember*, *Nightwatch* (collide with Signal, Ember.js, Nightwatch.js); *Sentinel* (Microsoft/Redis Sentinel); *AI Without Borders* as the product name (MSF-adjacent, and we cite MSF as a source — implies affiliation we don't have) |
| D11 | **Demo language is French** (resolves Q1) | Whisper large-v3 is ~5–6% WER on French vs 37.8% on Levantine and 84.7% on Maghrebi Arabic. The commonly quoted ~9.3% "Arabic" figure averages MSA read-speech benchmarks that do not represent a field clinician, who speaks a dialect. Translation quality is also nearly double (CoVoST-2 →EN BLEU 38.1 vs 21.4). At one word in three wrong, a live Arabic transcript is a demo failure. French also avoids RTL bidi work in the UI. Evidence in `DATASETS.md` §3.1 |
| D12 | **Image datasets are TBX11K + COVID-19 Radiography Database**, both CC BY 4.0 | CC BY 4.0 is the only licence in the survey that cleanly permits a *publicly posted* video for a *commercially pitched* product. TBX11K adds bounding boxes (something to point at on stage) and 4-level severity labels (the only clean-licensed way to sanity-check a 0–100 score). MIMIC-CXR, VinDr-CXR, PadChest, CheXpert and RSNA are all disqualified — see `DATASETS.md` §6 |
| D13 | **Consultation audio is self-recorded**, not sourced | No public clinical consultation audio exists in French or Arabic — the gap is absolute. Self-recording is therefore both necessary and the cleanest licence position. `PriMock57` supplies the consultation structure as a script template only |
| D14 | **WHO case definitions are paraphrased into our own schema**, with the WHO adaptation disclaimer | WHO material is CC BY-NC-SA 3.0 IGO and the NC clause is a genuine risk given the pitch names paying customers. Paraphrasing clinical criteria (facts/standards) into our own fields, plus the exact required disclaimer and no WHO logo, is the defensible position. ICD-11 is CC BY-ND (no adaptation of codes) and SNOMED CT needs an affiliate licence, so we use internal codes with a documented mapping. See `DATASETS.md` §4 |
| D15 | **Agent reasoning is `gemma4:12b`, not Nemotron 3 Super** (resolves Q2) | Nemotron is not on the box and nothing was downloaded; the venue cannot fetch it. `gemma4:12b` is the only model verified end-to-end through OpenClaw. Footprint with all models resident is ~13.6GB of the ≤70GB budget, so co-residency — the actual pitch — is preserved with room to spare. If Nemotron arrives on the drive it is a one-line config change (`OUTPOST_AGENT_MODEL`) |
| D16 | **Agent narration is asynchronous, not inline** | Measured OpenClaw turn time on this box ranged 20s–165s. Inline that blows the 30s heartbeat and, worse, makes cycle time unpredictable. The alert is written immediately with a deterministic rationale and the wording is upgraded in place once OpenClaw replies. Severity, case ids, counts and trend are decided by arithmetic *before* the model is consulted, so invariant 5 holds whether narration runs or not. Adds `alerts.rationale_source`; `ARCHITECTURE.md` §3 amended |
| D17 | **Orchestration is a supervisor script, not Docker** | Ollama holds the models resident on the host GPU. Containerising Outpost would need host networking plus GPU passthrough to reach it — more failure modes on demo day, no fewer. `scripts/run_demo.sh` delivers what Docker was wanted for (one command, ordered startup, health checks, clean teardown) with nothing new to debug at 17:00 |
| D18 | **UI listens on port 8081** | 8080 is already bound by the OpenShell gateway on this box |

---

## Third-party content — clearance and citation

Everything below must be cleared and declared in the writeup (Rule 06). Full licence
analysis, exact clauses and rejected alternatives are in [`DATASETS.md`](DATASETS.md).

| Asset | Source | Clearance | Cited where |
| --- | --- | --- | --- |
| Chest X-rays (demo) | TBX11K (Nankai Univ.) + COVID-19 Radiography Database (Qatar Univ.) | ✅ **CC BY 4.0** — commercial + public video OK | Writeup + README + `DATASETS.md` §9 |
| Chest X-rays (testing) | NIH ChestX-ray14, Kaggle sample | ✅ **"No restrictions"** + required attribution | Writeup + `DATASETS.md` §9 |
| Chest X-rays — rejected | MIMIC-CXR, VinDr-CXR, PadChest, CheXpert, RSNA | ⛔ Credentialing / DICOM / size / NC — see `DATASETS.md` §6 | — |
| Consultation audio | **Self-recorded in French** (D11, D13) | ✅ Self-authored — no public clinical audio exists in FR/AR | — |
| ASR validation corpora | MediaSpeech FR; African Accented French (OpenSLR 57) | ✅ **CC BY 4.0** / **Apache 2.0** | Writeup + `DATASETS.md` §9 |
| Translation scoring | CoVoST 2 fr→en | ⚠️ **CC BY-NC** — offline validation only, never on camera | — |
| Note-style reference | Indiana Open-i; PriMock57 | ⚠️ **NC / research licence** — structure only, never on camera | — |
| Background graph | Synthetic, scripted | ✅ Self-authored | — |
| Cluster cases | Synthetic, designed to trip the threshold | ✅ Self-authored | — |
| WHO syndromic case definitions | WHO/UXH/EPR/2023.1, paraphrased into our own schema (D14) | ⚠️ **CC BY-NC-SA 3.0 IGO** — requires the adaptation disclaimer, no WHO logo, no implied endorsement | `case_definitions.source_note` + deck + `DATASETS.md` §4.2 |
| WHO TB CAD recommendation | WHO consolidated TB guidelines, Module 2, 2021, Rec. 14 | ✅ Cite for the "thresholds calibrated per setting" claim | Deck + `DATASETS.md` §4.4 |
| Model weights (Whisper large-v3, MedGemma 4B, Nemotron, embeddings) | Vendor licences | ⬜ **To confirm** — see `DATASETS.md` §10 item 3 | Writeup stack declaration |

---

## How to record a decision

Append a row to the decision log with the rationale in one sentence. If it changes an
invariant in `../AGENTS.md` or a contract in `ARCHITECTURE.md`, update that file in the
same commit.
