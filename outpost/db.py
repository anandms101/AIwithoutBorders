"""SQLite connection, schema and migrations (``docs/ARCHITECTURE.md`` §3).

One database, WAL mode, always on disk. AGENTS.md invariant 7: a crash 20
minutes before the pitch must not lose the pre-populated graph.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from outpost.config import Settings, settings

# Verbatim from ARCHITECTURE §3. Amend that document in the same commit as any
# change here.
SCHEMA = """
-- Job queue (F-01)
CREATE TABLE IF NOT EXISTS jobs (
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
CREATE TABLE IF NOT EXISTS artifacts (
  case_id           TEXT PRIMARY KEY,
  native_transcript TEXT,                  -- F-02, source language
  english_text      TEXT,                  -- F-02, translation
  source_language   TEXT,
  audio_path        TEXT,
  image_path        TEXT,
  film_score        INTEGER,               -- F-03, 0-100
  film_findings     TEXT,                  -- F-03, short text, NEVER used for alerting
  syndrome_code     TEXT,                  -- F-04
  syndrome_conf     REAL,
  catchment         TEXT,
  created_at        TEXT NOT NULL
);

-- Graph (F-05). Not Neo4j.
CREATE TABLE IF NOT EXISTS nodes (
  id         TEXT PRIMARY KEY,             -- 'patient:p-014', 'visit:v-221', 'syndrome:awd'
  type       TEXT NOT NULL CHECK (type IN ('patient','visit','syndrome')),
  label      TEXT,
  attrs_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
  src        TEXT NOT NULL REFERENCES nodes(id),
  dst        TEXT NOT NULL REFERENCES nodes(id),
  rel        TEXT NOT NULL,                -- 'had_visit', 'presented_as'
  created_at TEXT NOT NULL,
  PRIMARY KEY (src, dst, rel)
);

-- Denormalised surveillance view: the ONLY table alert logic reads
CREATE TABLE IF NOT EXISTS cases (
  case_id       TEXT PRIMARY KEY,
  patient_id    TEXT NOT NULL,
  syndrome_code TEXT NOT NULL,
  catchment     TEXT NOT NULL,
  film_score    INTEGER,
  occurred_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cases_window
  ON cases (syndrome_code, catchment, occurred_at);

-- Case-definition RAG (F-04)
CREATE TABLE IF NOT EXISTS case_definitions (
  code        TEXT PRIMARY KEY,            -- 'acute_watery_diarrhoea'
  title       TEXT NOT NULL,
  definition  TEXT NOT NULL,               -- paraphrased from WHO, cite source
  source_note TEXT NOT NULL,
  embedding   BLOB NOT NULL                -- float32 vector
);

-- Trace: this table IS the trace panel (F-08, NFR auditability)
CREATE TABLE IF NOT EXISTS trace (
  id             INTEGER PRIMARY KEY,
  ts             TEXT NOT NULL,
  cycle_id       TEXT,
  actor          TEXT NOT NULL,            -- 'agent' | 'worker:asr' | ...
  tool           TEXT NOT NULL,
  args_json      TEXT NOT NULL,
  result_summary TEXT,
  duration_ms    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_trace_ts ON trace (id DESC);

-- Alerts (F-07, F-09, F-10)
CREATE TABLE IF NOT EXISTS alerts (
  id             TEXT PRIMARY KEY,
  severity       TEXT NOT NULL,
  syndrome_code  TEXT NOT NULL,
  catchment      TEXT NOT NULL,
  case_ids_json  TEXT NOT NULL,
  window_hours   INTEGER NOT NULL,
  trend          TEXT,
  rationale_text TEXT NOT NULL,
  status         TEXT NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','dismissed')),
  bytes_sent     INTEGER,
  created_at     TEXT NOT NULL,
  decided_at     TEXT
);
"""

TABLES = (
    "jobs",
    "artifacts",
    "nodes",
    "edges",
    "cases",
    "case_definitions",
    "trace",
    "alerts",
)


def utcnow() -> str:
    """Timestamp format used across every table."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(config: Settings | None = None) -> sqlite3.Connection:
    """Open the database with the pragmas Outpost relies on."""
    config = config or settings
    config.ensure_dirs()

    connection = sqlite3.connect(
        config.db_path,
        timeout=30.0,
        isolation_level=None,  # explicit transactions
    )
    connection.row_factory = sqlite3.Row
    # WAL lets the heartbeat read while the workers write, which PRD §7
    # concurrency requires, and survives a hard kill.
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def init_db(config: Settings | None = None) -> Path:
    """Create the schema. Idempotent — safe to run on every start."""
    config = config or settings
    with connect(config) as connection:
        connection.executescript(SCHEMA)
    return config.db_path


@contextmanager
def transaction(
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> Iterator[sqlite3.Connection]:
    """Run a unit of work atomically.

    Opens (and closes) its own connection when one is not supplied.
    """
    owned = connection is None
    conn = connection or connect(config)
    try:
        conn.execute("BEGIN")
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
    finally:
        if owned:
            conn.close()


def table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return {row["name"] for row in rows}


if __name__ == "__main__":
    path = init_db()
    with connect() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        present = sorted(table_names(conn) & set(TABLES))
    print(f"database   = {path}")
    print(f"journal    = {mode}")
    print(f"tables     = {len(present)}/{len(TABLES)} {present}")
