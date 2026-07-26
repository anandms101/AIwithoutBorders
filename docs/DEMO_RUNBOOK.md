# Outpost — Demo Runbook

Five minutes on stage, one 3-minute recorded video. One spine, one irreducible piece of
theatre. Demo + pitch is 30% of the score.

---

## The 5-minute script

**0:00** — Walk to the box. **Unplug the ethernet.** Hold it up, set it on the table in
front of the judges.
> *"Everything you're about to see runs with that unplugged."*

**0:10** — South Sudan, 1999. Two thousand deaths. The system built in response is still
paper.

**0:35** — The gap, one slide, one fact: MSF's most-requested telemedicine specialty is
radiology; reads take days.

**1:10** — The demo, **on the box, not slides**:
- Three consultations dropped into the watched folder on camera — audio, X-ray, note.
- Agent picks them up unprompted. **Nobody touches the keyboard.**
- Trace panel: translates → scores the film → retrieves the case definition → queries the
  graph → reasons about signal versus noise.
- Alert fires. Clinician view with linked cases and reasoning. Approve.
- Sync window opens. **On-screen counter: `2.7 GB on box · 340 bytes transmitted`.** Cut to
  the patient records still sitting there.

**3:30** — Why this machine — four models resident, unified memory, concurrent workloads,
deskside power. Then:
> *"every deployment is one more of these boxes."*

**4:20** — Close:
> *"It triages, it never diagnoses. And this can't be built on cloud inference — not because
> we'd rather not, but because cloud inference requires uploading the exact thing we're
> protecting. The cable stays out."*

---

## Choreography

- **Record the 3-minute video by 17:00–18:00, not 18:25.** It's the artifact that survives
  if the live demo dies.
- **Exactly one thing is unscripted live:** dropping the files in. Models warm, graph
  pre-populated with two weeks of ordinary consultations so the cluster trips on three new
  arrivals against real noise.
- **Recorded fallback cued on the second monitor.** If the box hiccups: *"I'll show you the
  recording"* — and keep talking.
- **Demo language: French or Arabic.** Core MSF operating languages, well-supported by the
  ASR. Do not pick something exotic and produce garbage on stage.
- **Put the box on the table**, not behind the podium.
- The person reading the pitch should not be debugging at 17:00.

---

## Pre-flight checklist (run at 16:30 and again before going on)

- [ ] `ollama ps` — 4 models resident, keep-alive infinite
- [ ] `nvidia-smi` — ≥20% memory headroom
- [ ] Heartbeat process running; idle cycle < 10s
- [ ] UI up and responsive while the heartbeat runs (concurrency is a scored claim)
- [ ] Background graph pre-populated (2 weeks of ordinary consultations)
- [ ] `./scripts/reset_demo.sh` run clean, < 60s
- [ ] Three cluster case files staged on the drive, ready to drop
- [ ] Terminal ready showing a **blocked outbound request** to a non-allowlisted host
- [ ] Mock receiver reachable at the single allowlisted endpoint
- [ ] `bytes_on_box` and `bytes_sent` both rendering
- [ ] Recorded video cued on second monitor, audio level checked
- [ ] Ethernet cable accessible for the unplug moment

---

## Evidence to have on screen

| Claim | Evidence |
| --- | --- |
| Runs local, always-on | Cable unplugged; heartbeat ticking in the trace panel |
| Four models co-resident | `ollama ps` output |
| Default-deny egress | Terminal showing a denied non-allowlisted request |
| Agent, not cron | Trace panel: tool calls in sequence with arguments |
| Minimal egress | `2.7 GB on box · 340 bytes transmitted` counter |
| Thresholds are real | Negative case: same syndrome spread across catchments → no alert |

---

## Q&A prep

**"Isn't this a cron job?"**
→ It chooses what to examine, calls tools, reasons about coincidence versus cluster, drafts
clinical language. Point at the trace.

**"What about false alarms?"**
→ The human gate exists for exactly that. Per-setting threshold calibration is already
WHO's requirement for CAD. We shorten time-to-investigation; we don't declare outbreaks.

**"MSF has internet in most projects."**
→ Correct, and not our argument. Ours is data sensitivity plus specialist latency plus
intermittency. Records implying violence can't leave regardless of bandwidth.

**"Is this a medical device?"**
→ No, and designed not to be. Triage and prioritisation, human in the loop on every path.

**"Who pays?"**
→ Three tiers: lighthouse CSR/accessibility budgets, remote industrial medicine at scale,
and hardware pull-through for Dell and NVIDIA. See `ONE_PAGER.md` §Who pays.

**"Why not the 120B model?"**
→ The box can run the 120B — but the product needs four models hot at once, and that's the
better use of the memory.

---

## Failure handling on stage

| If this breaks | Say this, do this |
| --- | --- |
| Files don't get picked up | *"I'll show you the recording"* — switch to monitor 2, keep narrating |
| Alert doesn't fire | Show the trace panel reasoning and the pre-existing alert; move on |
| UI is unresponsive | Fall back to the terminal trace output — it's the same log |
| Model unloaded / slow | Do not wait on stage. Cut to the recording. |

Never debug in front of judges. The recording is the answer to every failure.
