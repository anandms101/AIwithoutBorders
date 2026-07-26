# Outpost — Architecture & Contracts

Working contract derived from `PRD.md` §4–§7. **Amend this file when the implementation
diverges** — this is the reference every worker and the agent code against. Nothing here
overrides the invariants in `../AGENTS.md`.

---

## 1. Repository layout (target)

```
.
├── AGENTS.md                  # standing context for every agent/human
├── .github/copilot-instructions.md
├── docs/                      # this folder — one-pager, PRD, plan, runbook, decisions
├── outpost/
│   ├── config.py              # all config, read from env, single source
│   ├── db.py                  # SQLite connections, migrations, schema DDL
│   ├── watcher.py             # F-01 inotify watcher on /data/inbox
│   ├── workers/
│   │   ├── asr.py             # F-02 Whisper large-v3, speech → English
│   │   ├── vision.py          # F-03 MedGemma 4B, film → score + findings
│   │   ├── casedef.py         # F-04 embedding retrieval over WHO definitions
│   │   └── graph_writer.py    # F-05 patient/visit/syndrome nodes + edges
│   ├── agent/
│   │   ├── heartbeat.py       # F-06 30s loop
│   │   ├── tools.py           # query_graph, get_case_def, score_film, raise_alert
│   │   └── alerting.py        # F-07 threshold logic + rationale drafting
│   ├── egress.py              # F-10 allowlisted POST, aggregate counts only
│   ├── trace.py               # tool-call audit log (feeds the trace panel)
│   └── web/
│       ├── app.py             # FastAPI, server-rendered
│       └── templates/         # Jinja: inbox, trace, alert review, byte counter
├── scripts/
│   ├── seed_background_graph.py   # 2 weeks of synthetic ordinary consultations
│   ├── seed_case_definitions.py   # WHO syndromic definitions → vector table
│   ├── drop_demo_cases.sh         # copies the 3 cluster cases into /data/inbox
│   ├── reset_demo.sh              # idempotent reset, must complete in < 60s
│   └── verify_egress_block.sh     # prove default-deny on camera
├── mock_receiver/             # the single allowlisted endpoint (runs off-box)
└── data/                      # gitignored: inbox/, artifacts/, outpost.db
```

## 2. Filesystem contract

| Path | Purpose |
| --- | --- |
| `/data/inbox/` | Watched folder. Clinicians drop `.wav/.m4a`, `.png/.jpg`, `.txt` here. |
| `/data/artifacts/<case_id>/` | Persisted per-case outputs: source copy, transcripts, findings JSON. |
| `/data/outpost.db` | SQLite — jobs, graph, vectors, trace, alerts. On disk, always. |

Files are grouped into a **case** by filename stem: `case-0421.wav`, `case-0421.png`,
`case-0421.txt` all belong to case `case-0421`. Dedupe on **SHA-256 content hash** — a file
dropped twice must not create a second case (`PRD.md` §F-07 detail: alert logic).

## 3. SQLite schema (single DB, WAL mode)

```sql
-- Job queue (F-01)
CREATE TABLE jobs (
  id            INTEGER PRIMARY KEY,
  case_id       TEXT NOT NULL,
  path          TEXT NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('audio','image','note')),
  content_hash  TEXT NOT NULL UNIQUE,      -- dedupe
  status        TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued','running','done','failed')),
  attempts      INTEGER NOT NULL DEFAULT 0,
  error         TEXT,
  enqueued_at   TEXT NOT NULL,
  started_at    TEXT,
  finished_at   TEXT
);

-- Worker outputs, one row per case
CREATE TABLE artifacts (
  case_id          TEXT PRIMARY KEY,
  native_transcript TEXT,                  -- F-02, source language
  english_text     TEXT,                   -- F-02, translation
  source_language  TEXT,
  audio_path       TEXT,
  image_path       TEXT,
  film_score       INTEGER,                -- F-03, 0-100
  film_findings    TEXT,                   -- F-03, short text, NEVER used for alerting
  syndrome_code    TEXT,                   -- F-04
  syndrome_conf    REAL,
  catchment        TEXT,
  created_at       TEXT NOT NULL
);

-- Graph (F-05). Not Neo4j.
CREATE TABLE nodes (
  id         TEXT PRIMARY KEY,             -- 'patient:p-014', 'visit:v-221', 'syndrome:awd'
  type       TEXT NOT NULL CHECK (type IN ('patient','visit','syndrome')),
  label      TEXT,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);
CREATE TABLE edges (
  src        TEXT NOT NULL REFERENCES nodes(id),
  dst        TEXT NOT NULL REFERENCES nodes(id),
  rel        TEXT NOT NULL,                -- 'had_visit', 'presented_as'
  created_at TEXT NOT NULL,
  PRIMARY KEY (src, dst, rel)
);
-- Denormalised surveillance view: the ONLY table alert logic reads
CREATE TABLE cases (
  case_id       TEXT PRIMARY KEY,
  patient_id    TEXT NOT NULL,
  syndrome_code TEXT NOT NULL,
  catchment     TEXT NOT NULL,
  film_score    INTEGER,
  occurred_at   TEXT NOT NULL
);
CREATE INDEX idx_cases_window ON cases (syndrome_code, catchment, occurred_at);

-- Case-definition RAG (F-04)
CREATE TABLE case_definitions (
  code        TEXT PRIMARY KEY,            -- 'acute_watery_diarrhoea'
  title       TEXT NOT NULL,
  definition  TEXT NOT NULL,               -- paraphrased from WHO, cite source
  source_note TEXT NOT NULL,
  embedding   BLOB NOT NULL                -- float32 vector
);

-- Trace: this table IS the trace panel (F-08, NFR auditability)
CREATE TABLE trace (
  id         INTEGER PRIMARY KEY,
  ts         TEXT NOT NULL,
  cycle_id   TEXT,
  actor      TEXT NOT NULL,                -- 'agent' | 'worker:asr' | ...
  tool       TEXT NOT NULL,
  args_json  TEXT NOT NULL,
  result_summary TEXT,
  duration_ms INTEGER
);

-- Alerts (F-07, F-09, F-10)
CREATE TABLE alerts (
  id             TEXT PRIMARY KEY,
  severity       TEXT NOT NULL,
  syndrome_code  TEXT NOT NULL,
  catchment      TEXT NOT NULL,
  case_ids_json  TEXT NOT NULL,
  window_hours   INTEGER NOT NULL,
  trend          TEXT,
  rationale_text TEXT NOT NULL,
  rationale_source TEXT NOT NULL DEFAULT 'template'
                 CHECK (rationale_source IN ('template','agent')),
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','dismissed')),
  bytes_sent     INTEGER,
  created_at     TEXT NOT NULL,
  decided_at     TEXT
);
```

**Amendment — `rationale_source`.** Agent narration is asynchronous. Measured OpenClaw
turn time on this box ranged from 20s to 165s, which would blow the F-06 heartbeat budget
and make cycle time unpredictable. So an alert is created immediately with a deterministic
template rationale (`rationale_source='template'`) and the wording is upgraded in place
once OpenClaw replies (`'agent'`). Only the prose changes: severity, case ids, counts,
trend and the egress payload are all decided by arithmetic before the model is consulted,
so **invariant 5 holds whether or not narration ever runs**.

**Invariant:** `alerting.py` may query `cases` and `case_definitions` only. It must never
read `artifacts.english_text`, `artifacts.native_transcript`, or `artifacts.film_findings`.
Free text cannot manufacture an outbreak.

## 4. Agent tools

Four tools, all logged to `trace` before and after execution.

```python
query_graph(syndrome_code: str | None, catchment: str | None, window_hours: int) -> {
    "count": int,
    "cases": [{"case_id": str, "occurred_at": str, "catchment": str, "film_score": int|None}],
    "baseline_count": int,       # same window length, preceding period — signal vs noise
}

get_case_def(query: str) -> {
    "code": str, "title": str, "definition": str, "source_note": str, "score": float
}

score_film(case_id: str) -> {"case_id": str, "score": int, "findings": str}

raise_alert(severity: str, syndrome: str, case_ids: list[str],
            window_hours: int, rationale_text: str) -> {"alert_id": str}
```

**Agent output schema** (`PRD.md` §F-07):
`{severity, syndrome, case_ids[], window, rationale_text}`

**Alert trigger:** ≥3 cases, same `syndrome_code`, same `catchment`, rolling 72h window.
Fewer than 3 → no alert. Spread across catchments → no alert. Thresholds are configurable
per setting (`config.py`), because per-setting calibration is WHO's stated requirement.

## 5. Model boundaries — strict JSON in, strict JSON out

Every model call is prompted with an explicit schema, parsed, validated, and has a
deterministic fallback. Never let unparseable prose reach the database.

| Worker | Output schema | Fallback when unparseable |
| --- | --- | --- |
| ASR (F-02) | `{"source_language": str, "native_transcript": str, "english_text": str}` | Retry once, then mark job `failed` and surface in trace |
| Vision (F-03) | `{"score": int 0-100, "findings": str}` | Fixed score `50`, `findings: "unscored — manual review required"` |
| Case-def (F-04) | `{"code": str, "confidence": float}` | Top-1 embedding match; if RAG is cut at the 15:00 gate, hardcoded keyword map |

## 6. Egress contract (F-10)

Exactly one allowlisted host. Payload is counts only, under 1KB:

```json
{"syndrome":"acute_watery_diarrhoea","catchment":"sector-4","count":11,"window_hours":72,"trend":"rising","site_id":"OP-001"}
```

Rules:
- Serialised from a frozen dataclass with **exactly** these six fields. No `**kwargs`, no
  passthrough dict, no debug fields.
- A unit test asserts the payload contains no `case_id`, no name, no age, no free text, and
  is `< 1024` bytes.
- `bytes_sent` is recorded on the alert row and rendered in the UI next to `bytes_on_box`.
- Egress only ever runs from the Approve handler. No other call site.

## 7. Runtime processes

| Process | Command (target) | Notes |
| --- | --- | --- |
| Watcher + workers | `python -m outpost.watcher` | Long-running; picks up jobs |
| Agent heartbeat | `python -m outpost.agent.heartbeat` | Every 30s; < 10s per idle cycle |
| Web UI | `uvicorn outpost.web.app:app --host 0.0.0.0 --port 8080` | Foreground; must not block on the heartbeat |
| Mock receiver | `python -m mock_receiver` (off-box) | The single allowlisted endpoint |

Heartbeat and UI must run **simultaneously** and be shown doing so (`PRD.md` §7
concurrency).

## 8. Configuration

All config in `config.py`, read from environment with sane defaults. Required:

```
OUTPOST_DB=/data/outpost.db
OUTPOST_INBOX=/data/inbox
OUTPOST_ARTIFACTS=/data/artifacts
OUTPOST_SITE_ID=OP-001
OUTPOST_HEARTBEAT_SECONDS=30
OUTPOST_ALERT_MIN_CASES=3
OUTPOST_ALERT_WINDOW_HOURS=72
OUTPOST_EGRESS_URL=http://<mock-receiver>:9000/report   # the ONLY allowlisted host
OLLAMA_HOST=http://127.0.0.1:11434
OLLAMA_KEEP_ALIVE=-1
OLLAMA_MAX_LOADED_MODELS=4
```

## 9. Verification commands

Run these before the dry runs; they are also the on-camera evidence.

```bash
ollama ps                       # 4 models resident, keep-alive infinite
nvidia-smi                      # memory headroom >= 20%
./scripts/verify_egress_block.sh  # non-allowlisted request DENIED
./scripts/reset_demo.sh         # idempotent, < 60s
./scripts/drop_demo_cases.sh    # the one unscripted moment
```
