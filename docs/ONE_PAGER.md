# Outpost — One-Pager

*Always-on clinical triage and outbreak surveillance for disconnected field hospitals —
running entirely on the Dell Pro Max with GB10.*

> Name locked — see `DECISIONS.md` D10. A field hospital *is* an outpost: forward-deployed,
> disconnected, self-sufficient. Say it in the deck as *"a clinical outpost that never
> sleeps."*

---

## The problem

In 1999, in South Sudan, a six-month delay in responding to a relapsing fever outbreak
killed more than 2,000 people. WHO built EWARN in response. Twenty-seven years later, that
system still runs on paper forms, manual case-definition matching, and a human counting
cases toward a threshold.

Meanwhile, the most frequent request on MSF's telemedicine platform is for radiologists.
Specialist reads take days. Complex cases wait for a weekly video call that sometimes
can't connect at all.

Both problems have the same shape: **the clinical signal already exists at the point of
care, and nobody can act on it fast enough.**

## The product

A clinician works normally — dictates a consultation in their own language, uploads an
X-ray from the portable unit, writes a note. Everything lands in a watched folder on the
box.

Outpost runs continuously, unprompted, and:

| Step | What happens |
| --- | --- |
| **Listen** | Speech-to-English translation in one pass. Source audio, native transcript, and English kept side by side for clinician verification. |
| **Look** | Medical vision model scores the film, producing a calibrated abnormality score rather than prose. |
| **Structure** | Maps each presentation onto formal WHO syndromic case definitions — the step that currently requires a trained surveillance officer. |
| **Remember** | Links the patient into a longitudinal graph, resolving returning patients who arrive with no ID and inconsistent name spellings. |
| **Watch** | Detects clusters across patients, across days, against real background noise. |
| **Escalate** | Threshold trips → clinician on shift is alerted in minutes, with the linked cases and the agent's reasoning. |
| **Gate** | A human approves before anything leaves. What crosses the wire is aggregate counts: *"eleven cases of acute watery diarrhoea, sector 4, past 72 hours, rising."* Never a record. |

WHO already ships a physical product called **"EWARS in a box"** for surveillance in
settings without reliable internet or power. **This is the version that thinks.**

## Why it cannot run in the cloud

Not a preference. Three structural reasons:

1. **The data can get patients killed.** MSF's own data policy classifies as highest-risk
   any record implying criminal conduct or exposing patients to serious risk including
   death — explicitly naming violence-related data such as gunshot wounds, sexual violence
   records, and data from detention settings. In a conflict zone the threat model is not a
   compliance auditor; it's a combatant with legal process. No BAA addresses that.
2. **One remote call breaks the whole chain.** The pipeline is multimodal — speech, vision,
   retrieval, reasoning. If any single stage is an API call, the audio, the image, and the
   note all have to leave. Multi-model is what makes local-first load-bearing.
3. **Cloud models are a moving target.** Providers deprecate and silently update. Clinical
   triage behaviour changing underneath you without revalidation is unauditable. A frozen
   local model version inside the NemoClaw sandbox — default-deny, allowlisted endpoints,
   sandboxed writes — is reproducible.

**The architecture's punchline:** the most valuable thing the system produces is also the
only thing safe to transmit. Privacy and usefulness point the same direction.

## Why this machine

- **Always-on forbids model swapping.** Four models resident simultaneously — ASR, vision,
  embeddings, reasoning. If the heartbeat pages models in and out, load time dominates and
  the loop stops being continuous. Co-residency is a memory-capacity requirement; 128GB is
  what buys it.
- **Unified memory for imaging.** DICOM arrays are large; no PCIe copy between pipeline
  stages.
- **Two workloads at once.** Background surveillance sweeps while a clinician works in the
  foreground. Independent review of this exact box found sustained background agent loops
  with no noticeable foreground impact.
- **Power budget.** Field sites run on generators and solar. A deskside box deploys where a
  rack does not.

## Why always-on

Four behaviours impossible without persistence — only the first is the demo:

1. **Outbreak surveillance** — inherently requires watching across days.
2. **Overnight backlog** — the day's films and notes process while nobody's there; the
   morning handover report is already written.
3. **Opportunistic sync** — waits for the connectivity window, pushes the prioritised
   digest. Nobody has to be awake.
4. **Longitudinal linkage** — returning patients resolve into the graph over time.

*It's not a cron job:* the agent chooses what to examine, calls tools, reasons about
coincidence versus cluster, and drafts the clinical language. The trace panel in the demo
is the evidence.

## Who pays

| Tier | Buyer | Why |
| --- | --- | --- |
| **Lighthouse** | CSR / accessibility budgets at BigTech, hospital networks, health systems | Fast yes, low friction, generates the reference deployment |
| **Scale** | Remote industrial medicine — rigs, mines, cruise lines, expedition and research stations | Duty-of-care obligations, real medical budgets, identical technical constraints |
| **For Dell and NVIDIA** | Hardware pull-through | Every clinic, camp, rig, and ship that deploys this is one more GB10 sold into a segment that currently buys nothing. The software is the reason the box gets purchased. |

## Safety posture

**It triages and prioritises. It never diagnoses.**

- Every output is a draft for a clinician; every escalation path has a human gate.
- Alerts fire on structured fields a human can inspect — never on raw translated free
  text, so a hallucinated clause cannot manufacture an outbreak.
- Thresholds are calibrated per setting, which is already WHO's stated requirement for
  computer-aided detection.
- Model versions frozen and auditable inside the sandbox.
- Goal is shorter time-to-investigation, not automated outbreak declaration.

## Rubric alignment

| Criterion | Weight | How we score |
| --- | --- | --- |
| Local-first + always-on | 30% | Heartbeat runs unattended across days; privacy is structural, not preferential; proven live with the cable out |
| Business value | 30% | Named buyers at three tiers, automates a WHO-standardised workflow that exists today, hardware pull-through for the sponsors |
| Demo + pitch | 30% | One spine, one irreducible piece of theatre, opening line with a body count, closing line that makes the architecture inevitable |
| Technical execution | 10% | Multi-model justified by the pipeline; only one unscripted moment on stage; recorded fallback |

## Explicitly out of scope

Named deliberately — this is discipline, not incompleteness.

Radiologist-grade reporting · multilingual ASR beyond the demo language · per-language
fine-tuning on-box · EMR and DHIS2 integration · deterioration monitoring for admitted
patients · multi-site federation.

---

## Sources worth citing in the deck

- WHO EWARS / EWARN, including "EWARS in a box" for settings without reliable internet or
  electricity — who.int/emergencies/surveillance
- South Sudan 1999 relapsing fever delay, >2,000 deaths — CDC *Emerging Infectious
  Diseases* 23(13), 2017
- WHO recommendation of computer-aided detection for TB screening since 2021, with
  per-population threshold calibration
- MSF telemedicine: radiology as most-requested specialty — doctorswithoutborders.org
- MSF data-sharing policy, sensitive-data classification — *PLOS Medicine*, Sheather et al.
- Dell Pro Max with GB10 sustained background agent loops — *Computer Weekly* review
