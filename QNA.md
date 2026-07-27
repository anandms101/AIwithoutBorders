# Q&A — questions we should expect

Answers grouped by who is asking. Every number here was measured on the box; where we are
weak, the honest answer is written out rather than dodged — a judge who finds a gap you
tried to hide stops believing the rest.

**Rules for answering:**
- If you don't know, say "I don't know, but here's how you'd find out."
- Never claim a capability we cut. The non-goals list is a strength; use it.
- Never say "diagnose", "detect disease", "confirm" or "rule out". Say **triage**,
  **prioritise**, **flag for review**, **abnormality score**.

---

## 1. The sceptical technologist

**"Is anything sent to the cloud?"**
No. `./scripts/verify_egress_block.sh` checks four things live: no hosted-LLM SDK
installed, no non-local URL anywhere in the runtime path, Ollama answering on
`127.0.0.1`, and the receiver rejecting anything outside the contract. Pull the network
cable and re-run the demo — nothing changes.

**"What if the model hallucinates an outbreak?"**
It structurally cannot. Alerts fire on `COUNT(*)` over structured fields. The model is
handed already-verified numbers and asked only to phrase them. A test asserts narration
changes no decision field. **Turn the model off entirely and the identical alert fires**
with the same severity and the same case IDs.

**"So what is the LLM actually doing? Sounds like you don't need it."**
Fair challenge. For the *alert decision*, correct — that's arithmetic, deliberately. The
models do the work models are good at: turning French speech into English, reading a chest
film, and mapping free-text presentations onto WHO case definitions. Without them you have
a spreadsheet that a clinician has to fill in by hand, which is exactly the paper workflow
EWARN runs on today.

**"Isn't this just a cron job?"**
It picks what to examine, calls tools, reasons about coincidence versus cluster, and drafts
clinical language. The trace panel shows the tool calls in sequence. But the honest part:
the *threshold* is deterministic, and that's a safety decision, not a limitation.

**"How do you know the threshold isn't hardcoded to fire?"**
Two decoys ship with the demo. `case-0424` is the same syndrome in a different catchment;
`case-0425` is a different syndrome in the same catchment. Both are processed, both map
correctly, **neither contributes**. That's the demo's own control group.

**"Does this scale?"**
Cluster detection over **50,000 cases across 90 days runs in 19ms** — indexed SQL on
`(syndrome_code, catchment, occurred_at)`. The bottleneck is ASR at ~18s per recording on
CPU, which is a GPU move away. One field hospital does ~40 consultations a day, so we are
three orders of magnitude inside the envelope.

**"Why SQLite and not a real database / Neo4j?"**
One box, one process group, no network. SQLite in WAL mode gives durability and concurrent
read-while-write, which is all we need. A graph database would be a second service to
provision, back up and debug at 17:00 — the graph here is two tables and a join.

---

## 2. The clinician or epidemiologist

**"What is a catchment and why does the operator pick it?"**
The geographic area a patient came from — a camp sector, a village. It's what makes a
cluster meaningful: three cases of watery diarrhoea across three sectors is background;
three in *one* sector suggests a shared water source.

The operator picks it because it **must not be inferred from the consultation text**. If a
model read "sector 4" out of a transcript, a mistranscription or hallucinated clause could
place cases in a sector they didn't come from and manufacture an outbreak. It enters as
structured data from registration, exactly as it would in a real clinic.

**"Three cases is a very low threshold."**
It's configurable, and that's the point — WHO's own guidance requires thresholds to be
**calibrated locally** to population and setting. Three is right for a demo and for a small
catchment; a district hospital would set it higher. Severity is also derived from the rise
over baseline, not the raw count: three means nothing if the previous 72 hours also had
three.

**"What about false alarms?"**
That's what the human gate is for. Nothing transmits without an explicit Approve. We are
shortening time-to-investigation, not declaring outbreaks. A false alarm costs one
clinician five minutes; a missed cluster costs considerably more.

**"Is this a medical device?"**
No, and it's designed not to be. It triages and prioritises; it never diagnoses. Every
output is a draft for a clinician and every escalation path has a human gate. The alert
text says "cases matching", never a disease name.

**"Would you trust MedGemma to read a chest X-ray?"**
Not to diagnose — and we don't ask it to. It produces a 0–100 **review priority score** so
a clinician looks at the most concerning film first instead of in arrival order. If the
output is unparseable it falls back to a fixed 50 and "unscored — manual review required".
It never silently guesses.

**"Whisper on accented or dialect speech is unreliable."**
Correct, and it drove a decision. We demo in **French** (~5–6% WER) rather than Arabic
(37.8% Levantine, 84.7% Maghrebi). At one word in three wrong, an Arabic transcript would
be a demo failure and a clinical hazard. That's a documented limitation, not something we
have solved.

---

## 3. Privacy, safety and ethics

**"What actually leaves the box?"**
124 bytes. Six fields: syndrome, catchment, count, window, trend, site ID. Against roughly
3.9 MB held locally — a ratio of about **31,500 : 1**. The payload is previewed on screen
*before* anyone approves it.

**"How do I know a patient identifier can't leak?"**
Three independent guards. The payload is a frozen dataclass with exactly six fields, so
there is no `**kwargs` for a field to slip through. `send` has exactly one call site,
enforced by a test that greps every other module. And the receiver returns **422** for any
field outside the contract — demonstrated live in the locality check.

**"Patient data on a public GitHub repo?"**
No patient data exists. Every case is synthetic and self-authored; the background graph is
generated by a script. Chest films are cached locally and gitignored.

**"Who is accountable when it gets something wrong?"**
The clinician, as now. Every escalation requires human approval, and every tool call is
logged with timestamp and arguments — the trace *is* the audit record. We can reconstruct
exactly what the system saw and when.

**"What about consent?"**
Out of scope for a hackathon build, and it would matter in deployment. The relevant design
property is that identifiable data never leaves the box, so consent for *transmission*
concerns aggregate counts only.

---

## 4. Product and commercial

**"MSF has internet in most projects."**
True, and not our argument. Ours is data sensitivity plus specialist latency plus
intermittency. Records implying violence or persecution can't leave the country regardless
of bandwidth.

**"Who pays?"**
Three tiers: lighthouse deployments funded from CSR and accessibility budgets; remote
industrial medicine — mines, rigs, ships — at scale; and hardware pull-through for Dell and
NVIDIA. Detail in `docs/ONE_PAGER.md`.

**"Why does this need a GB10 rather than a laptop?"**
Four models resident simultaneously so the heartbeat is continuous rather than paying model
load on every cycle. That's a memory-capacity requirement. Current footprint is ~13.6 GB
against a ≤70 GB budget, so there is headroom for larger models.

**"Why not the 120B model?"**
The box can run it. But the product needs four models hot at once, and co-residency *is*
the pitch — a 87 GB model starves the other three.

---

## 5. Hard questions — where we are weak

Answer these plainly. They are more convincing than the strengths.

**"Two patients with the same filename would merge into one case."**
Correct, and we verified it. Cases group by filename stem, so `case-0421.txt` written twice
with different content produces one case with two notes. In deployment the filename comes
from the registration system and is a patient identifier, so collisions don't arise. For
the demo it's a real sharp edge and we'd fix it by keying on registration ID rather than
filename.

**"Your syndrome mapping is an embedding lookup over ten definitions."**
Yes. It gets 8/8 on held-out presentations, and below a confidence floor it returns
`unmapped` rather than guessing — because a wrong syndrome code feeds straight into cluster
detection. It is not a clinical NLP system and we don't claim it is.

**"You're using gemma4, not the Nemotron the PRD specifies."**
Correct. Nemotron isn't on this box and the venue can't download it. gemma4:12b is the only
model verified end-to-end through OpenClaw. It matters less than it sounds: that model only
rewords an alert arithmetic already decided, and swapping it is one environment variable.

**"Your X-rays aren't from the cleared datasets."**
Right — they're cached from a mirror for development. TBX11K and the COVID-19 Radiography
Database are both CC BY 4.0 and cleared in `docs/DATASETS.md`; they swap in from the drive
without a code change.

**"The agent takes two minutes. That's not real-time."**
It is, and that's why narration is off the critical path. The alert is written immediately
from arithmetic; OpenClaw only improves the wording afterwards. The heartbeat's own idle
cycle is under one second against a ten-second budget.

**"What happens when Ollama dies mid-demo?"**
Every model boundary has a deterministic fallback. Vision returns a fixed 50 and "unscored".
Syndrome mapping falls back to a keyword map. Alerts use a template rationale. The system
degrades to something correct and visibly says so in the trace, rather than crashing or
silently inventing values.

**"Have you tested this on real patients / real outbreak data?"**
No. It's a hackathon build validated on synthetic cases and public radiographs. The next
step is a retrospective evaluation against a real EWARN dataset to calibrate thresholds and
measure false-positive rates — which is exactly the work per-setting calibration requires.

---

## 6. Quick reference

| Question | One-line answer |
| --- | --- |
| Anything to the cloud? | No — 4 checks, live, one of them a 422 denial |
| What leaves? | **124 bytes**, 6 fields, after human approval |
| Kept : sent | ~**31,500 : 1** |
| Alert rule | ≥3 cases, same syndrome, same catchment, 72h — configurable |
| Can the LLM cause an alert? | No — arithmetic decides, model only phrases |
| Models | medgemma · whisper large-v3 · embeddinggemma · gemma4 |
| Memory | ~13.6 GB of ≤70 GB |
| Scale | 50k cases → clusters in **19 ms** |
| Tests | **272** + 8 live model tests |
| Diagnoses? | **Never.** Triage and prioritisation only |

---

## 7. If you're stuck

Three answers that are always available and always true:

1. **"Let me show you"** — the trace panel, the decoys, or the locality script.
2. **"That's deliberately a non-goal"** — and cite `AGENTS.md`. Scope discipline is a
   strength.
3. **"I don't know — here's how we'd find out."** Better than a confident wrong answer,
   especially in a clinical context.

Deeper detail: `docs/ARC.md` (what's built and measured), `docs/DECISIONS.md` (why),
`docs/DATASETS.md` (licensing).
