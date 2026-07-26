# Decisions & Open Questions

Two sections: **open questions** that block work, and a **decision log** that records what
was chosen and why. Update this file the moment a question is answered — an unanswered
question here means someone is guessing.

---

## Open questions — resolve by 11:30

| # | Question | Why it blocks | Owner | Status |
| --- | --- | --- | --- | --- |
| Q1 | **Demo language — French or Arabic?** | Drives ASR testing; must be tested with real recorded audio by 13:00 | ML-A | ⬜ Open |
| Q2 | **Final Nemotron variant and actual resident size after quantization** | Determines whether all 4 models fit under the ≤70GB budget | Infra | ⬜ Open |
| Q3 | **Product name** (FieldSignal is a placeholder) | Appears in UI, repo, deck, video | Presenter | ⬜ Open |
| Q4 | **Where does the mock egress receiver live** — a teammate's laptop on the venue network, or a second local port? (Laptop is more convincing on camera.) | Sets the allowlist entry and `FIELDSIGNAL_EGRESS_URL` | Infra | ⬜ Open |
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

---

## Third-party content — clearance and citation

Everything below must be cleared and declared in the writeup (Rule 06).

| Asset | Source | Clearance | Cited where |
| --- | --- | --- | --- |
| Chest X-rays | NIH ChestX-ray14 / VinDr-CXR, public de-identified. **Load from drive.** | ⬜ To confirm | Writeup + README |
| Consultation audio | Self-recorded by the team in French or Arabic | ✅ Self-authored | — |
| Background graph | Synthetic, scripted | ✅ Self-authored | — |
| Cluster cases | Synthetic, designed to trip the threshold | ✅ Self-authored | — |
| WHO syndromic case definitions | Paraphrased into our own schema | ⬜ Cite source | `case_definitions.source_note` + deck |
| Model weights (Whisper large-v3, MedGemma 4B, Nemotron, embeddings) | Vendor licences | ⬜ To confirm | Writeup stack declaration |

---

## How to record a decision

Append a row to the decision log with the rationale in one sentence. If it changes an
invariant in `../AGENTS.md` or a contract in `ARCHITECTURE.md`, update that file in the
same commit.
