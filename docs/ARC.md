# ARC — Outpost Implementation Record

> **What this is.** A record of what is actually built, how each piece works, what it does
> when things go wrong, and the numbers we measured. Written so the pitch and the Q&A can
> be answered from evidence rather than intention.
>
> `PRD.md` says what we set out to build. **This file says what exists.** Where they
> differ, this file is right and the divergence is called out.
>
> Last updated: through the F-10 egress contract and synthetic demo data.

---

## 1. One-line

An always-on clinical agent for disconnected field hospitals that turns every consultation
into outbreak surveillance, with no patient data leaving the box.

## 2. What actually runs

```
demo_cases/*.txt ──► data/inbox/ ──watchdog──► jobs (SQLite)
                                                  │
                          ┌───────────────────────┼────────────────┐
                          ▼                       ▼                ▼
                    ASR + translate         vision scorer     case-def RAG
                    Whisper large-v3        medgemma          embeddinggemma
                          └───────────────────────┴────────────────┘
                                                  │
                                          artifacts (free text lives here, and stops here)
                                                  │
                                         graph_writer promotes STRUCTURED FIELDS ONLY
                                                  │
                                    nodes / edges  +  cases (surveillance view)
                                                  │
                                    heartbeat (30s) ──► threshold arithmetic
                                                  │
                                    alert (pending) ──► OpenClaw narrates, async
                                                  │
                                        HUMAN APPROVE (nothing moves without it)
                                                  │
                                    egress: 124 bytes, 6 fields, one host
```

## 3. Status by requirement

| ID | Requirement | State | Evidence |
|---|---|---|---|
| F-01 | Watcher enqueues within 2s, dedupes | ✅ | Live inotify test asserts <2s; dedupe on SHA-256 |
| F-02 | Audio → English translation | ✅ | Real French speech, ~18s/utterance |
| F-03 | Image → score 0–100 + findings | ✅ | medgemma, ~0.9s, valid JSON |
| F-04 | Presentation → WHO case definition | ✅ | 8/8 on held-out presentations |
| F-05 | Case written to graph | ✅ | 3 nodes + 2 edges + 1 `cases` row, idempotent |
| F-06 | Heartbeat every 30s | ✅ | Idle cycle **<1s** against a 10s budget |
| F-07 | Alert with linked case ids + rationale | ✅ | Live: 1 alert from 3 cases, 2 decoys excluded |
| F-08 | UI live trace panel | ✅ | Auto-refreshing panel, newest first, errors highlighted |
| F-09 | Approve / Dismiss | ✅ | Approve transmits + records bytes; dismiss transmits nothing |
| F-10 | Aggregate egress, byte count shown | ✅ | **124 bytes**, previewed before approval; counters live |
| F-11 | Side-by-side transcripts (P1) | ✅ | `/case/<id>` shows native + English + film findings |
| F-12 | Returning-patient resolution (P2) | ⬜ | Not started — explicitly a nice-to-have |

**Test suite: 235 passing, plus 8 live model tests.**

## 4. How each part works, and what it does when it breaks

Every model boundary is *strict JSON in, strict JSON out, with a deterministic fallback*.
No model output ever reaches the database unvalidated.

### Watcher (F-01)
`watchdog` inotify on the inbox. Case id is the filename stem, so `case-0421.wav`,
`.png` and `.txt` are one case. Dedupe on SHA-256 content hash via a `UNIQUE` column.

**Non-obvious:** inotify fires on *create*, not close. A large file copied in is visible
long before it is complete, and hashing it immediately would record the hash of a partial
file — permanently poisoning dedupe so the real file is later dropped as a duplicate.
`wait_until_stable` blocks until the size stops changing.

**Degrades:** a bad file is logged to the trace and skipped; the watcher never dies.

### Vision (F-03) — `medgemma:latest`
Scores a chest film 0–100 for **review priority**. Never a diagnosis.

**Finding:** medgemma **is multimodal**, despite Ollama reporting `completion`-only
capability. The metadata is wrong; verified by sending an image and getting a correct
description back.

**Degrades:** any invalid output — out of range, wrong type, empty findings, model
unreachable — yields a fixed `50 / "unscored — manual review required"`. It never raises.
Validation explicitly rejects `True` as a score, since `bool` is an `int` subclass in
Python and a naive check would accept it.

### Case definitions (F-04) — `embeddinggemma:300m`
768-dim embeddings, cosine top-1 over 10 WHO syndromic definitions. Ten rows means a
linear scan is exact and instant; a vector index would be complexity with no payoff.

**Degrades:** below a confidence floor it returns `unmapped` rather than the best of a bad
set — a wrong syndrome code feeds straight into cluster detection, so an honest refusal is
safer than a confident guess. If embeddings are unavailable it falls back to a keyword map,
capped at 0.5 confidence so the coarse path can never outrank real retrieval.

### ASR (F-02) — Whisper large-v3 via CTranslate2
French per D11. Whisper's `translate` task always targets English, so native transcript
and translation are two decodes of the same audio.

**Degrades:** `local_files_only=True` is deliberate — a runtime download would hang at the
venue or silently break the offline guarantee. A missing cache fails loudly and names the
fetch script.

### Graph (F-05)
`nodes` + `edges` in SQLite, not Neo4j (D2), plus the denormalised `cases` table.

**The denormalisation is the load-bearing part.** `cases` is the only table alert logic
reads. Traversing the graph for clusters would work, but it would leave `artifacts` one
join away from the alert path. `cases` has no column capable of carrying narrative text.

### Heartbeat (F-06) and alerting (F-07)
Every 30s: drain jobs → promote to graph → evaluate thresholds.
**Trigger: ≥3 cases, same syndrome, same catchment, rolling 72h.**

Severity comes from the rise over baseline, not the raw count. Three cases means nothing
if the preceding 72h also had three.

**Degrades:** a failed job is marked failed and written to the trace, never swallowed.

### OpenClaw — the agent harness
Driven locally: `openclaw --no-color agent --local --session-key <k> --message <m>`,
configured against `http://127.0.0.1:11434/v1`. No SDK, no remote endpoint.

**The agent does not execute tools itself, and that is deliberate.** Tool dispatch stays in
Python; OpenClaw receives already-verified counts and turns them into prose. If the model
chose its own tool arguments it could request a window or catchment that manufactures a
cluster. The threshold decision must be arithmetic, not generation.

**Narration is asynchronous** — see §6.

### Egress (F-10)
`EgressPayload` is a frozen dataclass with **exactly six fields**. No `**kwargs`, no
passthrough dict. A dict would let a future edit add `case_id` in one line and nobody
would notice at review; the type makes the guarantee structural.

`send` has exactly one call site — `approve_alert`. Two tests enforce it: one greps this
module, one greps every other module in the package.

## 5. Measured numbers

Taken from real runs on the GB10 box, not estimates.

| Metric | Value |
|---|---|
| **Egress payload** | **124 bytes** (limit 1024) |
| **Bytes on box vs sent** | **230,619 : 124** — a **1,860:1 ratio** |
| Heartbeat, 5 jobs → 5 cases → 1 alert | **769 ms** |
| Idle heartbeat cycle | **<1s** (budget 10s) |
| Vision score, one film | ~0.9 s |
| Case-definition retrieval | 8/8 correct |
| ASR, one French utterance | ~18 s (CPU) |
| Seeding 10 case definitions | 6.8 s |
| `reset_demo.sh` | **1.5 s** (budget 60s) |
| Resident models | medgemma 2.9GB + embeddinggemma 0.68GB + gemma4 8.1GB ≈ **11.7GB** under Ollama, plus Whisper under CTranslate2 — ~13.6GB total of a ≤70GB budget |

## 6. Divergences from the plan — and why

Four. Each was forced by measurement, not preference.

**1. Nemotron 3 Super → `gemma4:12b` for agent reasoning.**
Nemotron is not on the box and nothing was downloaded. gemma4:12b is the only model
verified end-to-end through OpenClaw. *Resolves Q2.*

**2. Agent narration is asynchronous, not inline.**
Measured OpenClaw turn time ranged **20s to 165s**. Inline, that blows the 30s heartbeat
and makes cycle time unpredictable. So the alert is written immediately with a
deterministic rationale and the wording is upgraded in place once OpenClaw replies.
Severity, case ids, counts and trend are decided by arithmetic *before* the model is
consulted — a test asserts enrichment changes no decision field. **Invariant 5 holds
whether narration runs or not.** Added `alerts.rationale_source`; `ARCHITECTURE.md` §3 is
amended to match.

**3. `/data` → repo-local `./data`.**
`/data` needs root on this box. The path is env-overridable, which ARCHITECTURE §8 allows.

**4. Background graph stops short of the live alert window.**
At the ordinary consultation rate the background alone tripped the threshold and the demo
cluster was indistinguishable. This is the realistic shape anyway: the baseline period
carries the ordinary rate, the cluster arrives on top. The seeder exits non-zero if the
background would mask the demo.

## 7. The invariants, and how each is enforced

Not asserted — **checked**.

| Invariant | Enforcement |
|---|---|
| 1. No remote inference | Grep test: no non-local URLs in runtime code; no hosted-LLM SDK installed |
| 2. No patient data leaves | Six-field frozen dataclass; tests seed a name and age into a rationale and assert neither survives |
| 3. Human gate | `send` has one call site (`approve_alert`), enforced by two grep tests |
| 4. Triage, never diagnose | Prompt tests assert "do not diagnose" and "not a diagnosis" stay in the vision prompt |
| 5. Structured fields only | Test greps `alerting.py` for `english_text`, `native_transcript`, `film_findings` — all absent. `cases` has no text column |
| 6. Models stay resident | `keep_alive=-1` on every Outpost request; `make demo` warms all three Ollama models; `ollama ps` shows `UNTIL=Forever`. OpenClaw's own calls don't set it, so `make keepalive` (systemd, sudo) is the belt-and-braces fix |
| 7. Durable state | SQLite WAL; `PRAGMA foreign_keys=ON` set explicitly and tested |
| 8. Every tool call logged | Row written *before* execution and completed after, including on exception |

## 8. Bugs found and fixed while building

Worth having ready — they demonstrate the tests are load-bearing.

**Window boundary off-by-one-day.** `occurred_at` is ISO-8601
(`2026-07-26T12:00:00+00:00`); SQLite's `datetime()` renders `2026-07-26 12:00:00`.
Compared as raw strings, `T` (0x54) sorts above space (0x20) — so a case **73 hours old
counted as inside a 72-hour window**. This would have silently inflated every cluster and
fired false alerts. Both sides now go through `datetime()`. Regression test pins 71h in,
73h out.

**`keep_alive` type.** Ollama rejects the *string* `"-1"` with `missing unit in duration`,
400-ing every call. It must be an integer.

**Context length, not parameter count, drives residency.** `ollama ps` showed
`phi4-mini:3.8b` holding **20GB** purely from a 131k default context. Pinning `num_ctx`
dropped medgemma from 3.8GB to 2.9GB.

**OpenClaw `maxTokens` was the entire latency problem.** Uncapped output made one
narration take 67s; capped at 400 the model call is ~1s. But `contextWindow` cannot go to
8192 — OpenClaw's own system prompt exceeds it and every call then fails with "Context
overflow". 32768 is the working value.

**OpenClaw reports some failures on stdout with exit code 0.** Without screening,
"Context overflow: prompt too large" would have been stored as a clinician-facing alert
rationale.

**Lossy ASR text overwrote a good note-derived syndrome mapping.** A case can carry both a
written note and a dictated recording. Whisper rendered *"selles liquides"* as *"liquid
saline"*, which retrieved `acute_febrile_illness` instead of `acute_watery_diarrhoea` — and
because the recording finished second, the worse evidence won. Three clustering cases
silently became three unrelated ones and the alert stopped firing. The mapping now keeps
the highest confidence rather than the most recent, and traces the discarded one.

**Approved alerts re-fired every heartbeat.** Approving does not make the cases disappear,
so the same cluster raised an identical alert 30 seconds later, and every cycle after. That
is alert fatigue — the classic way a surveillance system stops being read. Suppression now
covers decided alerts too, but only while no new case has appeared in the group.

## 9. Likely questions

Full set, grouped by who is asking and including the ones where we are weak, is in
[`../QNA.md`](../QNA.md). The essentials:

**"Is anything sent to the cloud?"** No. `scripts/verify_egress_block.sh` proves it live in
four checks, one of which is the receiver returning 422 for a payload carrying an identifier.

**"What if the model hallucinates an outbreak?"** It structurally cannot. Alerts fire on
`COUNT(*)` over structured fields. The model is handed already-verified numbers and asked
only to phrase them; a test asserts its output changes no decision field. Turn the model
off entirely and the same alert fires with the same severity and the same case ids.

**"How do you know the threshold isn't just hardcoded to fire?"** Two decoys ship with the
demo: same syndrome in a different catchment, and a different syndrome in the same
catchment. Both are processed, both are mapped correctly, neither contributes.

**"Why not the 120B model?"** The product needs four models hot at once, and co-residency
is the pitch. Current footprint is ~13.6GB of a ≤70GB budget.

**"What happens if a doctor drops the same file twice?"** Dedupe is on SHA-256 content
hash, not filename, so a re-copy under a new name is still rejected. Verified live.

**"What actually leaves the box?"** 124 bytes: syndrome, catchment, count, window, trend,
site id. Against 230,619 bytes held locally. The receiver rejects anything else with 422.

## 10. Not built, deliberately

DICOM, radiologist-grade reports, more than one ASR language, EMR/DHIS2 integration,
auth/multi-user, deterioration monitoring, multi-site federation, any mobile client, any
SPA framework, Neo4j. All named as non-goals in `AGENTS.md`; the discipline is the point.

## 11. Still open

- **Q4** — where the mock receiver lives. Defaulting to `127.0.0.1:9000`; one env var.
- **Q5** — who reads the pitch.
- **F-12** — returning-patient resolution across name variants. Explicitly P2.
- **Chest X-ray datasets** — TBX11K / COVID-19 Radiography cleared in `DATASETS.md` but not
  downloaded. Vision is verified against synthetic images; real films are a swap, not a change.
- **Consultation audio** — D13 calls for self-recorded French. ASR is verified against
  MediaSpeech FR instead, which is the designated baseline; recording is a drop-in.
- **ASR on GPU** — currently CPU at ~18s/utterance. Inside budget, but improvable.

## 12. How to run it

```bash
make setup && make demo      # preflight, reset, start all four services
make drop                    # the unscripted moment
```

Dashboard on <http://127.0.0.1:8081/>, receiver on <http://127.0.0.1:9000/reports>.
`make stop` tears everything down. Full instructions in the README.

Orchestration is a supervisor script rather than Docker (D17): Ollama holds the models on
the host GPU, so containerising Outpost would need host networking plus GPU passthrough —
more failure modes on demo day, not fewer. `run_demo.sh` preflights the venv, Ollama, each
required model, OpenClaw and both ports before starting anything, so a missing model
surfaces as a specific message rather than a half-started system.
