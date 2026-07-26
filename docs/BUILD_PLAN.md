# Outpost — Build Plan

Working copy of `PRD.md` §9. **Re-read the non-goals list at every gate.**
Timebox: demo video + submission by **18:30**, pitch deck by **19:00**, code freeze at
video submission.

---

## Milestones and gates

### now → 11:30 · Box provisioned
**Owner: Infra**

- [ ] **Verify drive contents before touching anything else.** Models not on the drive is
      the one fatal risk — venue Wi-Fi cannot download them.
- [ ] Docker 28+ and NVIDIA container runtime present
- [ ] `nemoclaw onboard` — OpenShell sandbox, inference routing, filesystem + network policy
- [ ] Ollama serving on all interfaces (systemd drop-in)
- [ ] Load 4 models from drive; preload and pin weights
- [ ] `OLLAMA_KEEP_ALIVE=-1`, `OLLAMA_MAX_LOADED_MODELS>=4`; confirm with `ollama ps`
- [ ] Egress allowlist set to exactly one host; **verify a non-allowlisted request is denied**
- [ ] Resolve open questions 1–5 in `DECISIONS.md`

> **Cut line:** if models aren't hot by 11:30, drop to 3 models and cut the embedding/RAG
> step (F-04 falls back to a hardcoded syndrome map).

### 11:30 → 13:30 · Spine end-to-end on one file
**Owners: Infra + Backend**

- [ ] F-01 watcher on `/data/inbox`, enqueue within 2s, dedupe on content hash
- [ ] SQLite schema created (jobs, artifacts, nodes, edges, cases, trace, alerts)
- [ ] One worker running end-to-end on a single file, artifact persisted
- [ ] **13:00 hard checkpoint:** ASR tested with *real recorded audio* in the demo
      language. Not at 17:00. This is a High risk.

### 13:30 → 15:00 · All workers + agent loop
**Owners: ML-A, ML-B, Backend/Agent**

- [ ] F-02 ASR → native transcript + English translation, one pass
- [ ] F-03 vision → score 0–100 + short findings (strict JSON schema, validated, fallback)
- [ ] F-04 case-definition mapping
- [ ] F-05 case written to graph with timestamp + catchment
- [ ] F-06 heartbeat every 30s, queries graph, evaluates thresholds
- [ ] F-07 alert raised with linked case IDs + rationale (structured fields only)
- [ ] Agent tool definitions wired: `query_graph`, `get_case_def`, `score_film`, `raise_alert`
- [ ] Every tool call written to `trace`

> **15:00 gate:** if a case doesn't flow end-to-end, cut F-04 and hardcode syndrome mapping.
> P1 items are only unlocked if P0 is green at 15:00.

### 15:00 → 16:30 · UI
**Owner: Frontend (shared, whoever finishes first)**

- [ ] Inbox view
- [ ] F-08 live trace panel — tool calls in sequence
- [ ] F-09 alert review with Approve / Dismiss
- [ ] F-10 Approve → allowlisted POST, aggregate counts only, byte size displayed
- [ ] `bytes_on_box` counter next to `bytes_sent`
- [ ] F-11 (P1) audio + native transcript + English side by side

> **16:00 gate:** if the trace panel isn't rendering, print tool calls to a terminal and
> screen-capture that instead — **do not lose the trace**. It is 30% of the score.

### 16:30 → 17:15 · Data + dry runs

- [ ] Pre-populate background graph: 2 weeks of synthetic ordinary consultations
- [ ] Seed the 3 synthetic cluster cases designed to trip the threshold
- [ ] Seed WHO case definitions (paraphrased, cited)
- [ ] `reset_demo.sh` idempotent and < 60s
- [ ] **Full dry run, twice.** Fix what breaks.
- [ ] Negative case ready if time allows: cases spread across catchments → no alert

### 17:15 → 18:00 · Record the video
**Non-negotiable — start recording at 17:15 even if P1 items are unfinished.**

- [ ] Max 3 minutes, tight cuts, everything working
- [ ] Cue the recording on the second monitor as the live-demo fallback

### 18:00 → 18:30 · Submit

- [ ] Writeup: what you built, value to companies, **declare your stack per Rule 06**
- [ ] Demo video file uploaded (max 3 min)
- [ ] GitHub URL (required)
- [ ] Third-party content cleared and cited (X-ray datasets, models, WHO definitions)
- [ ] Confirm demo runs on the box with no remote API calls in the runtime path
- [ ] **Submit at 18:15, not 18:29**

### 18:30 → 19:00 · Pitch deck

- [ ] Built from `ONE_PAGER.md`; sources listed at the end of that file

---

## Workstream ownership (4 builders)

| Stream | Scope |
| --- | --- |
| **Infra** | Box setup, NemoClaw/OpenShell, model loading, egress policy, deployment |
| **ML-A** | ASR + translation worker |
| **ML-B** | Vision scorer + case-definition mapping |
| **Backend/Agent** | Graph schema, heartbeat, agent tools, alert logic |
| **Frontend** | UI and trace panel (shared, whoever finishes first) |

**If 3 builders:** Infra absorbs Frontend, and ML-A takes case-definition mapping.

---

## Standing risk register

| Risk | Severity | Mitigation | Owner |
| --- | --- | --- | --- |
| Models not on drive; venue Wi-Fi can't download them | **Fatal** | Verify drive contents *before* anything else | Infra |
| Model swapping kills heartbeat continuity | High | `KEEP_ALIVE=-1`, verify `ollama ps` under load | Infra |
| ASR output is garbage in chosen language | High | French or Arabic only; test real audio by 13:00 | ML-A |
| Scope creep back to five features | High | Non-goals list is binding; re-read at every gate | All |
| Vision model produces prose, not a score | Medium | Strict JSON schema prompt; parse, validate, fixed-score fallback | ML-B |
| Trace panel eats the whole afternoon | Medium | 30% of the score — protect it. Terminal output is acceptable | Frontend |
| Live demo dies on stage | Medium | Recorded video cued on second monitor; practice the handoff line | Presenter |

---

## Rule of thumb when stuck

`P0 (F-01…F-10)` → `P1 (F-11)` → `P2 (F-12)`. Take the cut line. Ship the trace panel.
Start recording at 17:15 regardless.
