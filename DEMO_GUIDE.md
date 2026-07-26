# DEMO GUIDE — run it on this machine, right now

Everything below is verified on **this box**. Models are pulled, weights cached, demo media
generated. No downloads needed.

Timings are measured, not estimated. **Read §0 and §6 before you present.**

---

## 0. The two things that will bite you

**1. ASR is slow — 15–20s per recording, and there are four.** After you drop the cases the
inbox sits at "running" for roughly **90–120 seconds** before the alert appears. That is
Whisper large-v3 on CPU. It is *not* broken. Fill the time by talking through the trace
panel, which is populating live the whole while. If you would rather not wait, use
`--notes-only` (§2, Option B) and the whole thing completes in **under 2 seconds**.

**2. OpenClaw narration takes 60–165s and lands *after* the alert.** This is by design, not
a stall — the alert is written immediately from arithmetic, and OpenClaw only rewords it.
The panel shows `template` first, then flips to `agent`. §5 turns that into a feature.

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

Open **<http://127.0.0.1:8081/>**. You should see **156 cases** already in the graph — two
weeks of synthetic background consultations, so cluster detection runs against realistic
noise rather than an empty table.

**Have these open before you present:**

| Window | What |
| --- | --- |
| Browser tab 1 | <http://127.0.0.1:8081/> — the dashboard |
| Browser tab 2 | <http://127.0.0.1:9000/reports> — the receiver, empty for now |
| Terminal 1 | for `make drop` |
| Terminal 2 | `watch -n2 ollama ps` — models resident, `UNTIL = Forever` |

If preflight fails it tells you exactly what is wrong. `make stop` then `make demo` clears
most things. If a port is stuck: `ss -tlnp | grep -E ':8081|:9000'`.

---

## 2. Drop the cases — the one unscripted moment

### Option A — the full multimodal demo (~2 min to alert)

```bash
make drop
```

```
==> Dropping cluster cases into ./data/inbox
    case-0421 -> txt wav jpg
    case-0422 -> txt wav
    case-0423 -> txt wav
==> Dropping decoys (these must NOT trigger an alert)
    case-0424 -> txt
    case-0425 -> txt wav jpg
```

### Option B — fast path, no waiting (~2 seconds to alert)

```bash
./scripts/drop_demo_cases.sh --decoys --notes-only
```

Notes only. Everything else is identical — same alert, same decoy exclusion, same egress.
**Use this if you are short on time or the room is restless.**

### Drag-and-drop instead (more convincing on camera)

The watcher is a real inotify watch on a real folder. Open the file manager at
`~/Documents/AIwithoutBorders/demo_cases`, open a second window at
`~/Documents/AIwithoutBorders/data/inbox`, and **drag the files across**. Say:

> "This is a watched folder. In the field a clinician just saves their file here. Nobody
> presses a button, and there is no upload — there is nowhere to upload to."

Drag `case-0421.txt`, `.wav` and `.jpg` together to show they become **one case**.

---

## 3. The dashboard, panel by panel

Point at these in order. Each one is a requirement being met.

### Inbox — grouped into cases
Five cases, each tagged with the modalities that arrived: **`audio` `film` `note`**.

> "Three files, one case. They group by filename stem, and they dedupe on content hash —
> drop the same file twice and it will not double-count into a cluster."

**Show the dedupe live** (it is a strong, cheap moment):

```bash
cp demo_cases/case-0421.txt data/inbox/case-0421-copy.txt
```

The case count does **not** change. The trace shows `duplicate hash=...`.

### Agent trace — live, no refresh
The panel polls every 2 seconds. You will see, in order:

`enqueue_file` → `transcribe` → `score_film` → `map_presentation` → `write_case` →
`query_graph` → `raise_alert`

> "Every tool call is logged before it runs and completed after, so a call that hangs or
> crashes still appears. This table *is* the audit log — it is not debug output we left in."

Errors render in red. There should be none, but if one appears, **point at it** — that is
the system refusing to hide a failure.

### Alerts — the escalation
One alert: **3 cases matching acute watery diarrhoea, sector-4, 72h, rising.**

> "Three cases, same syndrome, same catchment, inside 72 hours. Severity comes from the
> rise over baseline, not the raw count — three means nothing if last week also had three."

Note the wording: *cases matching*, *review recommended*, *thresholds calibrated per
setting*. **Never** a disease name, never "outbreak".

### The decoys — the part that proves the threshold is real
This is the strongest thing on the screen. Click into them.

| Case | Why it does **not** fire |
| --- | --- |
| `case-0424` | Same syndrome — but **sector-9**, a different catchment |
| `case-0425` | Same catchment — but **respiratory**, a different syndrome |

> "Both were processed. Both were mapped correctly. Neither contributes. If this were
> hardcoded to fire, these would have tripped it too."

### Case detail — click `case-0421`
Everything multimodal is here:

- **An audio player** — press play, it is French. *"Recorded by the clinician; it never left the box."*
- **French transcript and English translation, side by side** — Whisper large-v3, locally.
- **The actual chest radiograph**, with an abnormality score and findings.

> "Score, not diagnosis. It orders the queue for review. The clinician decides."

**Worth saying:** the note and the recording both map to a syndrome, and the system keeps
the *stronger* mapping, not the most recent. ASR text is lossier — "selles liquides" came
back as "liquid saline" — and letting the weaker evidence win just because it finished
second would have broken cluster detection. We hit that bug and fixed it.

### Byte counters — the number to land
Top right: **Bytes on box ≈ 3,900,000** vs **Bytes sent 0**.

---

## 4. Approve — the human gate

**Before pressing anything**, point at the box under the alert. It shows the exact payload
and its size, *before* transmission:

```json
{"catchment":"sector-4","count":3,"site_id":"OP-001",
 "syndrome":"acute_watery_diarrhoea","trend":"rising","window_hours":72}
```

> **124 bytes.** Six fields. No names, no ages, no free text, no case identifiers — the
> three case IDs collapsed to the number 3.

Press **Approve**. Switch to <http://127.0.0.1:9000/reports> — the aggregate has arrived.

Back on the dashboard: **Bytes sent 124**, and a **Kept : sent ratio of ~31,000:1**.

> "Roughly four megabytes of clinical data stayed. 124 bytes left, after a human approved
> it. That ratio *is* the product."

Mention **Dismiss** transmits nothing at all.

---

## 5. Showing OpenClaw

Two beats. The first is quick; the second is the interesting one.

### Beat 1 — it is real, and it is local

```bash
openclaw --version
grep -A2 '"ollama"' ~/.openclaw/openclaw.json | head -4
```

Shows `OpenClaw 2026.7.1-2` pointed at `http://127.0.0.1:11434/v1`. A loopback address.

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

## 6. Locality — the proof

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

## 7. Reset between runs

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

## 8. If something breaks on stage

| Symptom | Do this |
| --- | --- |
| Alert not appearing | ASR is still running. `make status`, then `tail -f .run/heartbeat.log`. Wait — 11 jobs take ~2 min. |
| Nothing in the inbox | `tail .run/watcher.log`. Restart: `make stop && make demo`. |
| Approve returns an error | The receiver is down. `curl 127.0.0.1:9000/health`. The alert stays **pending** — nothing is lost, just approve again. |
| Rationale stuck on `template` | OpenClaw is slow or absent. **The alert is complete and correct without it** — say so and move on. |
| Port already bound | `ss -tlnp \| grep -E ':8081\|:9000'`. Port 8080 is the OpenShell gateway, which is why we use 8081. |
| Total collapse | `make stop && make demo && ./scripts/drop_demo_cases.sh --decoys --notes-only` — under 60s to a working alert. |

**Fallback that always works:** `make test` — 233 tests, ~2 seconds, green. If the live demo
dies, run the suite and talk through what it proves.

---

## 9. Numbers to have memorised

| | |
| --- | --- |
| Egress payload | **124 bytes**, 6 fields, limit 1024 |
| Kept : sent | **~31,000 : 1** with media (1,859:1 notes-only) |
| Alert threshold | ≥3 cases, same syndrome, same catchment, 72h |
| Idle heartbeat | **<1s** against a 10s budget |
| Full pipeline, notes only | **769 ms** |
| Chest film scored | ~1.6s |
| One French recording | ~15–20s (CPU) |
| OpenClaw narration | 60–165s, **off the critical path** |
| Models resident | ~13.6 GB of a ≤70 GB budget |
| Tests | **233** + 8 live model tests |
| Background graph | 156 synthetic consultations, 14 days |

---

## 10. Regenerating demo media

Already generated and cached. Only needed on a fresh clone:

```bash
.venv/bin/python scripts/make_demo_cases.py     # notes + catchment manifest
.venv/bin/python scripts/make_demo_media.py     # French audio + films
```

Audio is synthesised locally with Piper — self-authored, no clearance needed, no network.
The radiographs are cached in `demo_media/` (gitignored: licence on that mirror is
unstated). **Before recording the video**, swap in TBX11K or the COVID-19 Radiography
Database from the USB drive — both CC BY 4.0 and cleared in `docs/DATASETS.md` §7 — and
re-run `make drop`.

---

## Related

- **[`docs/ARC.md`](docs/ARC.md)** — what is built, measured numbers, prepared Q&A answers.
  Read this before the judging round.
- [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md) — the 5-minute narrative script.
- [`README.md`](README.md) — install and architecture.
