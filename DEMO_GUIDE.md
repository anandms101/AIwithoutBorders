# DEMO GUIDE — run it on this machine, right now

Everything below is verified on **this box**. Models are pulled, weights cached, demo media
generated. No downloads needed.

Timings are measured, not estimated. **Read §0 and §6 before you present.**

---

## 0. The two things that will bite you

**1. ASR is slow — 15–20s per recording.** After dropping multimodal cases the pipeline
sits in "Local models" for **90–120 seconds** before the alert appears. That is Whisper
large-v3 on CPU. It is *not* broken, and the pipeline strip visibly shows it working the
whole time. If you would rather not wait, use `--notes-only` (§2, Option B) and the whole
thing completes in **under 2 seconds**.

**2. OpenClaw narration takes 60–165s and lands *after* the alert.** By design, not a
stall — the alert is written immediately from arithmetic and OpenClaw only rewords it. The
badge shows `template` first, then flips to `agent`. §6 turns that into the strongest
safety argument you have.

---

## 1. Start (≈40 seconds)

```bash
cd ~/Documents/AIwithoutBorders
make demo
```

Wait for:

```
==> Outpost is running
    Dashboard : http://127.0.0.1:8081/
```

`make demo` warms all three Ollama models on the way up, so `ollama ps` shows them resident
before anyone asks.

> **One-time, needs sudo — do this before the demo:** `make keepalive`
>
> Outpost pins its own model calls, but OpenClaw issues its own and doesn't, so the agent
> model can drop off `ollama ps` about five minutes after a narration. The systemd drop-in
> makes keep-alive the server-wide default and fixes it for every caller. Preflight prints
> a `note` if it isn't set.

Open **<http://127.0.0.1:8081/>**. You should see **156 cases** already in the graph — two
weeks of synthetic background consultations, so cluster detection runs against realistic
noise rather than an empty table.

**Have these open before you present:**

| Window | What |
| --- | --- |
| Browser tab 1 | <http://127.0.0.1:8081/> — the dashboard |
| Browser tab 2 | <http://127.0.0.1:9000/reports> — the receiver, empty for now |
| File manager | `~/Documents/AIwithoutBorders/demo_cases` — side by side with the browser, for dragging |
| Terminal | for the locality check in §7 |

If preflight fails it tells you exactly what is wrong. `make stop` then `make demo` clears
most things. If a port is stuck: `ss -tlnp | grep -E ':8081|:9000'`.

---

## 2. Drop the cases — the one unscripted moment

You have **two ways** to get files in. Do the browser one on camera; it *is* the doctor
workflow.

### Option A — drag and drop in the browser (the demo)

Open the file manager at `~/Documents/AIwithoutBorders/demo_cases`, put it side by side
with the dashboard, and **drag files straight onto the drop zone**.

**What is in that folder** — not every case has every modality, which is realistic; not
every patient gets a film:

| Case | Files | Role |
| --- | --- | --- |
| `case-0421` | `.txt` `.wav` `.jpg` | cluster — **drag this one first, it has all three** |
| `case-0422` | `.txt` `.wav` | cluster |
| `case-0423` | `.txt` `.wav` | cluster |
| `case-0424` | `.txt` | decoy — sector-9 |
| `case-0425` | `.txt` `.wav` `.jpg` | decoy — respiratory |
| `case-0426` | `.txt` `.wav` `.jpg` | **spare, for the live moment in §5** |
| `case-0427` … `0430` | `.txt` | spares, other syndromes and catchments |

> If you only see `.txt` files, the media was never generated. Run
> `.venv/bin/python scripts/make_demo_media.py` — about 3 seconds with the caches warm.
> `make demo` does this for you.

Then:

1. Set **Catchment** to `sector-4` on the drop zone.
2. Select `case-0421.txt`, `case-0421.wav` and `case-0421.jpg` and **drag them in together**.
3. The zone confirms: *3 file(s) → 1 case(s) in sector-4*.
4. Repeat with `case-0422.*` and `case-0423.*` (two files each).
5. Switch Catchment to `sector-9`, drag `case-0424.txt`.
6. Switch back to `sector-4`, drag `case-0425.*`.

> "Three files — a dictation, a chest film and a note — become one patient encounter,
> because they share a name. In the field the clinician just saves them. There is no
> upload button in the tent, and nowhere to upload to."

Point at **Catchment** while you do it:

> "Catchment is assigned at registration. It is never read out of the notes — if a language
> model could choose which catchment a case counted towards, generated text could
> manufacture a cluster."

### Option B — the scripted drop (fallback, and faster)

```bash
make drop                                              # full multimodal, ~2 min
./scripts/drop_demo_cases.sh --decoys --notes-only     # notes only, ~2 seconds
```

**Use `--notes-only` if the room is restless.** Same alert, same decoy exclusion, same
egress — just no audio or films to process.

### What lands either way

```
case-0421 -> txt wav jpg     ┐
case-0422 -> txt wav         ├─ cluster, sector-4
case-0423 -> txt wav         ┘
case-0424 -> txt             ─ decoy, sector-9   (same syndrome, wrong place)
case-0425 -> txt wav jpg     ─ decoy, sector-4   (same place, wrong syndrome)
```

Five more cases (`case-0426` … `case-0430`) are **held back deliberately** for §5.

---

## 3. The dashboard, top to bottom

The layout tells the story left to right. Walk it in order.

### The pipeline strip
Six stages: **Inbox → Local models → Case graph → Heartbeat → Human review → Egress.**
Each shows a live count and **lights up blue while it is working**; the arrows animate as
work flows between them.

> "That is the whole system. Files arrive, three local models extract from them, only
> structured fields reach the graph, a heartbeat watches for clusters, a human decides, and
> the only thing that leaves is a count."

Read the labels under the stages aloud — they are the guarantees, not decoration:
*structured fields only*, *nothing moves without it*, *counts only*.

### The header
**All inference local**, with the resident models and their sizes pulled live from Ollama.

> "Those are the models, on this box, right now. Nothing here calls out."

### Cases — files grouped by patient encounter
Each row tags the modalities that arrived: **`audio` `film` `note`**.

**Show the dedupe live** — cheap and convincing:

```bash
cp demo_cases/case-0421.txt data/inbox/case-0421-copy.txt
```

Case count does **not** move. The trace shows `duplicate hash=…`.

### Agent trace — live, no refresh
Polls every 2 seconds:

`enqueue_file` → `transcribe` → `score_film` → `map_presentation` → `write_case` →
`query_graph` → `raise_alert`

> "Every tool call is written before it runs and completed after, so a call that hangs or
> crashes still appears. This table *is* the audit log."

### Alerts
One: **3 cases matching acute watery diarrhoea, sector-4, 72h, rising.**

Note the wording — *cases matching*, *review recommended*, *thresholds calibrated per
setting*. Never a disease name.

### The decoys — the part that proves the threshold is real
| Case | Why it does **not** fire |
| --- | --- |
| `case-0424` | Same syndrome — but **sector-9** |
| `case-0425` | Same catchment — but **respiratory** |

> "Both processed, both mapped correctly, neither contributes. If this were hardcoded to
> fire, these would have tripped it."

### Case detail — click `case-0421`
- **Audio player** — press play, it is French
- **French transcript and English translation side by side**
- **The chest radiograph itself**, with score and findings

> "Score, not diagnosis. It orders the queue. The clinician decides."

---

## 4. Approve — the human gate

Under the alert, before you touch anything:

```json
{"catchment":"sector-4","count":3,"site_id":"OP-001",
 "syndrome":"acute_watery_diarrhoea","trend":"rising","window_hours":72}
```

> **124 bytes.** Six fields. No names, no ages, no free text — the three case IDs collapsed
> to the number 3.

Press **Approve**. The Egress stage lights up. Switch to
<http://127.0.0.1:9000/reports> — it has arrived.

Back on the dashboard: **Bytes sent 124**, and a **Kept : sent** ratio in the thousands.

> "Everything stayed. 124 bytes left, after a human approved it. That ratio *is* the
> product."

**Dismiss** transmits nothing at all.

---

## 5. The live moment — drag in a new case and watch it react

This is the strongest thing you can do on stage, because it cannot be pre-recorded.

**After approving the first alert**, drag `case-0426.txt`, `.wav` and `.jpg` onto the page
with catchment `sector-4`.

Watch the pipeline: **Local models** lights up as Whisper, MedGemma and the retriever all
run. Roughly 90 seconds later a **new alert** appears — now **four** cases.

> "I just added one patient. The cluster grew from three to four and the system raised it
> again, because there is new evidence a human has not seen. It did *not* re-raise the
> alert that was already approved — that would be alert fatigue, which is how a
> surveillance system stops being read."

Spares available: `case-0426`, `case-0427` (grow sector-4), and `case-0428`, `case-0429`,
`case-0430` (tuberculosis in sector-7, measles-like rash in sector-2, jaundice in
sector-1 — none disturb the sector-4 cluster).

---

## 6. Showing OpenClaw

Two beats. The first is quick; the second is the interesting one.

### Beat 1 — it is real, and it is local

```bash
openclaw --version
grep -A2 '"ollama"' ~/.openclaw/openclaw.json | head -4
ollama ps
```

Shows `OpenClaw 2026.7.1-2` pointed at `http://127.0.0.1:11434/v1` — a loopback address —
and three models resident with `UNTIL = Forever`. `make demo` warms them, so this is ready
before you ask.

> "Three models held in memory permanently, so the heartbeat never pays load time. Whisper
> is the fourth — it runs under CTranslate2 rather than Ollama, which is why it isn't in
> that list."

### Beat 2 — the rationale rewrites itself, live

When the alert appears its rationale is marked **`template`**. Leave the tab open. Within
about two minutes the badge flips to **`agent`** and the wording changes — OpenClaw has
finished and rewritten it.

Check it from the terminal:

```bash
.venv/bin/python -c "
from outpost.db import connect
with connect() as c:
    r=c.execute('SELECT rationale_source, rationale_text FROM alerts ORDER BY created_at DESC LIMIT 1').fetchone()
    print(r['rationale_source'], '->', r['rationale_text'][:160])"
```

And in the trace panel: `openclaw_narrate  264 chars in 123266ms`.

**The line to say:**

> "The agent took two minutes. The alert did not wait for it. Severity, the case list, the
> counts and the payload were all decided by arithmetic *before* the model was consulted —
> the model only chooses the wording. Turn OpenClaw off entirely and the identical alert
> still fires. A language model cannot invent an outbreak here, because it is never in the
> path that decides one."

That is the strongest safety claim in the project, and this is where you make it.

---

## 7. Locality — the proof

```bash
./scripts/verify_egress_block.sh
```

```
1. No hosted-LLM SDK installed          PASS
2. No non-local endpoint in runtime     PASS
3. Inference is served locally          PASS   (ollama ps: UNTIL = Forever)
4. Receiver refuses non-contract data   PASS   aggregate accepted (200)
                                        PASS   identifier DENIED (422)
```

Check 4 is the one to dwell on: a payload carrying `patient_name` is **rejected with 422**.

> "Even if we regressed and tried to send an identifier, the receiver refuses it. Privacy
> here is structural, not a promise."

**Pull the network cable and re-run the demo.** Nothing changes. That is the whole pitch in
one gesture.

---

## 8. Reset between runs

```bash
make stop && make demo      # ~40s, fresh background graph
make drop
```

`reset_demo.sh` takes **1.5 seconds** against a 60-second budget. You can run this between
takes without anxiety.

To re-record with different data:

```bash
.venv/bin/python scripts/seed_background_graph.py --seed 99
```

It **exits non-zero** if the random background would itself trip the threshold and mask
your demo cluster.

---

## 9. If something breaks on stage

| Symptom | Do this |
| --- | --- |
| **Only `.txt` files in `demo_cases/`** | Media was not generated: `.venv/bin/python scripts/make_demo_media.py` (~3s). |
| Alert not appearing | ASR is still running. `make status`, then `tail -f .run/heartbeat.log`. Wait — 11 jobs take ~2 min. |
| Nothing in the inbox | `tail .run/watcher.log`. Restart: `make stop && make demo`. |
| Approve returns an error | The receiver is down. `curl 127.0.0.1:9000/health`. The alert stays **pending** — nothing is lost, just approve again. |
| Rationale stuck on `template` | OpenClaw is slow or absent. **The alert is complete and correct without it** — say so and move on. |
| `ollama ps` shows fewer models than expected | A narration reloaded the agent model on Ollama's default timer. Re-run `make demo`, or `make keepalive` once with sudo to fix it permanently. |
| Port already bound | `ss -tlnp \| grep -E ':8081\|:9000'`. Port 8080 is the OpenShell gateway, which is why we use 8081. |
| Total collapse | `make stop && make demo && ./scripts/drop_demo_cases.sh --decoys --notes-only` — under 60s to a working alert. |
| Drag-and-drop not working | Fall back to `make drop` in a terminal. Same result, same pipeline. |

**Fallback that always works:** `make test` — 272 tests, ~3 seconds, green. If the live demo
dies, run the suite and talk through what it proves.

---

## 10. Numbers to have memorised

| | |
| --- | --- |
| Egress payload | **124 bytes**, 6 fields, limit 1024 |
| Kept : sent | **~31,500 : 1** with media (1,859:1 notes-only) |
| Alert threshold | ≥3 cases, same syndrome, same catchment, 72h |
| Idle heartbeat | **<1s** against a 10s budget |
| Full pipeline, notes only | **769 ms** |
| Chest film scored | ~1.6s |
| One French recording | ~15–20s (CPU) |
| OpenClaw narration | 60–165s, **off the critical path** |
| Models resident | 3 under Ollama (~11.7 GB) + Whisper under CTranslate2 |
| Tests | **272** + 8 live model tests |
| Background graph | 156 synthetic consultations, 14 days |
| Demo cases | 10 (3 cluster, 2 decoy, 5 spare for live drops) |

---

## 11. Regenerating demo media

`make demo` regenerates everything automatically. You only need these directly if you are
debugging:

```bash
.venv/bin/python scripts/make_demo_cases.py     # notes + catchment manifest
.venv/bin/python scripts/make_demo_media.py     # French audio + films  (~3s cached)
```

**`make clean` deletes `demo_cases/` but keeps the caches** (`demo_media/`, `.voices/`), so
regeneration stays offline and fast. Use `make clean-all` only if you want to force a
re-download — don't do that at the venue.

Audio is synthesised locally with Piper, so it is self-authored, needs no clearance, and
needs no network. The radiographs are cached in `demo_media/` (gitignored: the licence on
that mirror is unstated). **Before recording the video**, swap in TBX11K or the COVID-19
Radiography Database from the USB drive — both CC BY 4.0 and cleared in
`docs/DATASETS.md` §7 — and re-run `make demo`.

---

## Related

- **[`QNA.md`](QNA.md)** — questions to expect, grouped by who is asking, including the
  ones where we are weak. Read this before the judging round.
- **[`docs/ARC.md`](docs/ARC.md)** — what is built, measured numbers, how each part degrades.
- [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) — the 5-minute narrative script.
- [`README.md`](README.md) — install and architecture.
