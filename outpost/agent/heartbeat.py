"""F-06 — the heartbeat loop.

Runs every ``OUTPOST_HEARTBEAT_SECONDS`` (default 30):

1. drain queued jobs through the workers,
2. promote finished cases into the graph,
3. evaluate cluster thresholds and raise alerts.

**Budget: an idle cycle must complete in under 10s** (PRD §7), and the loop must
never block the UI. Two consequences shape this module:

* Every step is SQL and local model calls; nothing waits on the network.
* Agent narration is dispatched to a background thread by ``alerting.evaluate``
  and never awaited here. Measured OpenClaw turn time was 20s-165s, which would
  swallow the entire budget on its own.

Nothing is transmitted from this loop. Alerts land in ``pending`` and wait for a
human (invariant 3).
"""

from __future__ import annotations

import signal
import sqlite3
import time
from dataclasses import dataclass, field
from types import FrameType
from typing import Any

from outpost import trace
from outpost.agent import alerting
from outpost.config import Settings, settings
from outpost.db import connect, init_db, utcnow


@dataclass
class CycleResult:
    """What one heartbeat pass did."""

    cycle_id: str
    duration_ms: int
    jobs_processed: int = 0
    cases_written: int = 0
    alerts_raised: list[str] = field(default_factory=list)

    @property
    def idle(self) -> bool:
        return self.jobs_processed == 0 and not self.alerts_raised

    def summary(self) -> str:
        return (
            f"jobs={self.jobs_processed} cases={self.cases_written} "
            f"alerts={len(self.alerts_raised)} {self.duration_ms}ms"
            f"{' (idle)' if self.idle else ''}"
        )


def _claim_jobs(
    conn: sqlite3.Connection, limit: int
) -> list[sqlite3.Row]:
    """Take up to ``limit`` queued jobs and mark them running."""
    rows = conn.execute(
        "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT ?", (limit,)
    ).fetchall()
    for row in rows:
        conn.execute(
            "UPDATE jobs SET status = 'running', attempts = attempts + 1,"
            " started_at = ? WHERE id = ?",
            (utcnow(), row["id"]),
        )
    return rows


def _finish_job(
    conn: sqlite3.Connection, job_id: int, error: str | None = None
) -> None:
    conn.execute(
        "UPDATE jobs SET status = ?, error = ?, finished_at = ? WHERE id = ?",
        ("failed" if error else "done", error, utcnow(), job_id),
    )


def process_jobs(
    *,
    limit: int = 10,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> tuple[int, int]:
    """Run queued jobs through the workers. Returns (processed, cases_written)."""
    from outpost.workers import casedef, graph_writer, vision

    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        jobs = _claim_jobs(conn, limit)
        processed = 0
        touched_cases: set[str] = set()

        for job in jobs:
            try:
                if job["kind"] == "image":
                    vision.process(
                        job["case_id"], job["path"], connection=conn, config=config
                    )
                elif job["kind"] == "note":
                    from pathlib import Path

                    text = Path(job["path"]).read_text(errors="replace")
                    casedef.process(
                        job["case_id"], text, connection=conn, config=config
                    )
                elif job["kind"] == "audio":
                    from outpost.workers import asr

                    asr.process(
                        job["case_id"], job["path"], connection=conn, config=config
                    )
                _finish_job(conn, job["id"])
                touched_cases.add(job["case_id"])
                processed += 1
            except Exception as exc:
                # Never silently swallow on the demo path — it goes to the trace
                # and the job is marked failed so the UI can show it.
                _finish_job(conn, job["id"], f"{type(exc).__name__}: {exc}")
                trace.record(
                    "heartbeat",
                    "process_job",
                    {"job_id": job["id"], "case_id": job["case_id"]},
                    result_summary=f"ERROR {type(exc).__name__}: {exc}",
                    connection=conn,
                    config=config,
                )

        cases_written = 0
        for case_id in sorted(touched_cases):
            catchment = _catchment_for(conn, case_id, config)
            result = graph_writer.write_from_artifacts(
                case_id,
                _patient_for(conn, case_id),
                catchment,
                connection=conn,
                config=config,
            )
            if result is not None:
                cases_written += 1

        return processed, cases_written
    finally:
        if owned:
            conn.close()


def _catchment_for(
    conn: sqlite3.Connection, case_id: str, config: Settings
) -> str:
    """Catchment recorded by the worker, else the site default."""
    row = conn.execute(
        "SELECT catchment FROM artifacts WHERE case_id = ?", (case_id,)
    ).fetchone()
    if row and row["catchment"]:
        return str(row["catchment"])
    return config.site_id


def _patient_for(conn: sqlite3.Connection, case_id: str) -> str:
    """One patient per case for this build (F-12 resolution is a nice-to-have)."""
    row = conn.execute(
        "SELECT patient_id FROM cases WHERE case_id = ?", (case_id,)
    ).fetchone()
    return str(row["patient_id"]) if row else f"p-{case_id}"


def run_cycle(
    *,
    now: str | None = None,
    use_agent: bool = True,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> CycleResult:
    """One heartbeat pass."""
    config = config or settings
    cycle_id = trace.new_cycle_id()
    trace.set_cycle(cycle_id)
    started = time.perf_counter()

    owned = connection is None
    conn = connection or connect(config)
    try:
        trace.record(
            "heartbeat", "cycle_start", {"cycle_id": cycle_id}, connection=conn,
            config=config,
        )

        processed, cases_written = process_jobs(connection=conn, config=config)
        alerts = alerting.evaluate(
            now=now, use_agent=use_agent, connection=conn, config=config
        )

        result = CycleResult(
            cycle_id=cycle_id,
            duration_ms=int((time.perf_counter() - started) * 1000),
            jobs_processed=processed,
            cases_written=cases_written,
            alerts_raised=alerts,
        )

        trace.record(
            "heartbeat",
            "cycle_end",
            {"cycle_id": cycle_id},
            result_summary=result.summary(),
            duration_ms=result.duration_ms,
            connection=conn,
            config=config,
        )
        return result
    finally:
        trace.set_cycle(None)
        if owned:
            conn.close()


class _Stopper:
    """Cooperative shutdown so Ctrl-C ends the current cycle cleanly."""

    def __init__(self) -> None:
        self.stop = False

    def __call__(self, signum: int, frame: FrameType | None) -> None:
        self.stop = True


def run(config: Settings | None = None, max_cycles: int | None = None) -> None:
    """Run the heartbeat until interrupted."""
    config = config or settings
    init_db(config)

    stopper = _Stopper()
    signal.signal(signal.SIGINT, stopper)
    signal.signal(signal.SIGTERM, stopper)

    print(f"[heartbeat] interval : {config.heartbeat_seconds}s")
    print(f"[heartbeat] threshold: >={config.alert_min_cases} cases / "
          f"{config.alert_window_hours}h, same syndrome + catchment")
    print("[heartbeat] running — Ctrl-C to stop")

    cycles = 0
    while not stopper.stop:
        result = run_cycle(config=config)
        print(f"[heartbeat] {result.cycle_id} {result.summary()}")
        for alert_id in result.alerts_raised:
            print(f"[heartbeat]   ALERT {alert_id} — pending human review")

        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break

        # Sleep in slices so shutdown is responsive.
        for _ in range(config.heartbeat_seconds * 10):
            if stopper.stop:
                break
            time.sleep(0.1)

    print("\n[heartbeat] stopped")


def status(
    connection: sqlite3.Connection | None = None, config: Settings | None = None
) -> dict[str, Any]:
    """Counts for the UI header."""
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        def scalar(sql: str) -> int:
            return int(conn.execute(sql).fetchone()[0])

        return {
            "jobs_queued": scalar("SELECT COUNT(*) FROM jobs WHERE status='queued'"),
            "jobs_done": scalar("SELECT COUNT(*) FROM jobs WHERE status='done'"),
            "jobs_failed": scalar("SELECT COUNT(*) FROM jobs WHERE status='failed'"),
            "cases": scalar("SELECT COUNT(*) FROM cases"),
            "alerts_pending": scalar(
                "SELECT COUNT(*) FROM alerts WHERE status='pending'"
            ),
            "trace_rows": scalar("SELECT COUNT(*) FROM trace"),
        }
    finally:
        if owned:
            conn.close()


if __name__ == "__main__":
    run()
