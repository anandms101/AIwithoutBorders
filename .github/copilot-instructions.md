# Copilot instructions — FieldSignal

**`AGENTS.md` in the repository root is the canonical standing context. Read it first.**
It is loaded automatically alongside this file; everything below is a deliberately short
safety net, not a second copy. When the two disagree, `AGENTS.md` wins.

Project: an always-on clinical triage and outbreak-surveillance agent for disconnected
field hospitals, running entirely on a Dell Pro Max with GB10. Hackathon build (Dell x
NVIDIA Local AI). No patient data leaves the box.

## Detail lives in `docs/`

`ONE_PAGER.md` (pitch, rubric) · `PRD.md` (goals, non-goals, F-01…F-12, NFRs) ·
`ARCHITECTURE.md` (schema, tool signatures, egress contract) · `BUILD_PLAN.md` (gates,
cut lines) · `DEMO_RUNBOOK.md` (demo script, Q&A) · `DECISIONS.md` (open questions).

These are **not** auto-loaded — open the relevant one before acting. `AGENTS.md` says
which to read when.

## The four rules that must never be broken

The full list of eight invariants is in `AGENTS.md`. These four are the ones a well-meaning
change is most likely to violate:

1. **No remote inference in the agent runtime path.** All models run locally via Ollama /
   local serving inside the NemoClaw / OpenShell sandbox. Never add a hosted-model SDK,
   never call an external API, never download weights at runtime.
2. **Egress is one allowlisted host, aggregate counts only, after human approval.** No
   names, ages, free text, or identifiers may ever reach an outbound payload.
3. **Alert logic reads structured fields only** (syndrome code, timestamp, catchment, film
   score) — never transcripts, translations, or findings text.
4. **Triage and prioritise; never diagnose.** Every output is a draft for a clinician. In
   user-facing copy use "flag for review" / "abnormality score", never "diagnose",
   "confirm", "rule out", or a disease name in an alert.

## Before you write code

Check the **Current state** section of `AGENTS.md` — as of now there is no application
code in this repo, only documentation. The tree in `docs/ARCHITECTURE.md` §1 is the target
layout, not what exists. Do not assume modules, tests, or commands are present.
