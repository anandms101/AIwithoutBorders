"""Agent tools — signatures exactly as ``docs/ARCHITECTURE.md`` §4.

Four tools, all logged to ``trace`` before and after execution (invariant 8).

``query_graph`` reads ``cases`` only. It cannot reach ``artifacts`` free text,
which is invariant 5 — a hallucinated clause must not be able to manufacture an
outbreak. ``score_film`` is the single exception: it reads ``artifacts`` because
the film score *is* a structured field, and it returns findings for display to a
clinician, never for alert arithmetic.

``baseline_count`` is what turns a raw count into a signal. Three cases of
watery diarrhoea means nothing if the preceding 72h also had three; it means
a great deal if that period had none.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from typing import Any

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect, utcnow


def _resolve(
    connection: sqlite3.Connection | None, config: Settings | None
) -> tuple[sqlite3.Connection, bool, Settings]:
    config = config or settings
    if connection is not None:
        return connection, False, config
    return connect(config), True, config


def query_graph(
    syndrome_code: str | None = None,
    catchment: str | None = None,
    window_hours: int = 72,
    *,
    now: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> dict[str, Any]:
    """Count cases in a rolling window, with the preceding period as baseline.

    Reads ``cases`` only — never ``artifacts``.
    """
    conn, owned, config = _resolve(connection, config)
    try:
        trace_id = trace.record(
            "agent",
            "query_graph",
            {
                "syndrome_code": syndrome_code,
                "catchment": catchment,
                "window_hours": window_hours,
            },
            connection=conn,
        )
        started = time.perf_counter()

        anchor = now or utcnow()

        clauses = []
        extra: list[Any] = []
        if syndrome_code:
            clauses.append("syndrome_code = ?")
            extra.append(syndrome_code)
        if catchment:
            clauses.append("catchment = ?")
            extra.append(catchment)
        where_extra = ("" if not clauses else " AND " + " AND ".join(clauses))

        # occurred_at is ISO-8601 with a 'T' separator and a +00:00 offset;
        # datetime() renders 'YYYY-MM-DD HH:MM:SS'. Comparing those as raw
        # strings silently mis-bounds the window -- a case 73h old compares as
        # inside a 72h window because 'T' (0x54) sorts above ' ' (0x20). Both
        # sides must go through datetime().
        rows = conn.execute(
            "SELECT case_id, occurred_at, catchment, film_score FROM cases"
            " WHERE datetime(occurred_at) > datetime(?, ?)"
            "   AND datetime(occurred_at) <= datetime(?)"
            f"{where_extra}"
            " ORDER BY datetime(occurred_at)",
            [anchor, f"-{window_hours} hours", anchor, *extra],
        ).fetchall()

        # Same window length, immediately preceding — signal vs noise.
        baseline_row = conn.execute(
            "SELECT COUNT(*) FROM cases"
            " WHERE datetime(occurred_at) > datetime(?, ?)"
            "   AND datetime(occurred_at) <= datetime(?, ?)"
            f"{where_extra}",
            [
                anchor,
                f"-{window_hours * 2} hours",
                anchor,
                f"-{window_hours} hours",
                *extra,
            ],
        ).fetchone()

        result = {
            "count": len(rows),
            "cases": [
                {
                    "case_id": row["case_id"],
                    "occurred_at": row["occurred_at"],
                    "catchment": row["catchment"],
                    "film_score": row["film_score"],
                }
                for row in rows
            ],
            "baseline_count": int(baseline_row[0]),
        }

        trace.update(
            trace_id,
            result_summary=(
                f"count={result['count']} baseline={result['baseline_count']} "
                f"syndrome={syndrome_code} catchment={catchment}"
            ),
            duration_ms=int((time.perf_counter() - started) * 1000),
            connection=conn,
        )
        return result
    finally:
        if owned:
            conn.close()


def get_case_def(
    query: str,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> dict[str, Any]:
    """Retrieve the case definition best matching a free-text query."""
    from outpost.workers.casedef import map_presentation

    conn, owned, config = _resolve(connection, config)
    try:
        trace_id = trace.record(
            "agent", "get_case_def", {"query": query}, connection=conn
        )
        started = time.perf_counter()

        match = map_presentation(query, connection=conn, config=config)
        row = conn.execute(
            "SELECT code, title, definition, source_note FROM case_definitions"
            " WHERE code = ?",
            (match.code,),
        ).fetchone()

        result = {
            "code": match.code,
            "title": row["title"] if row else "",
            "definition": row["definition"] if row else "",
            "source_note": row["source_note"] if row else "",
            "score": round(match.confidence, 4),
        }

        trace.update(
            trace_id,
            result_summary=f"code={result['code']} score={result['score']}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            connection=conn,
        )
        return result
    finally:
        if owned:
            conn.close()


def score_film(
    case_id: str,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> dict[str, Any]:
    """Return the stored abnormality score for a case.

    Reads a *structured* field. The findings text comes back for the clinician
    to read; alert logic never consumes it.
    """
    conn, owned, config = _resolve(connection, config)
    try:
        trace_id = trace.record(
            "agent", "score_film", {"case_id": case_id}, connection=conn
        )
        started = time.perf_counter()

        row = conn.execute(
            "SELECT film_score, film_findings FROM artifacts WHERE case_id = ?",
            (case_id,),
        ).fetchone()

        result = {
            "case_id": case_id,
            "score": row["film_score"] if row and row["film_score"] is not None else None,
            "findings": row["film_findings"] if row and row["film_findings"] else "",
        }

        trace.update(
            trace_id,
            result_summary=f"case={case_id} score={result['score']}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            connection=conn,
        )
        return result
    finally:
        if owned:
            conn.close()


def raise_alert(
    severity: str,
    syndrome: str,
    case_ids: list[str],
    window_hours: int,
    rationale_text: str,
    *,
    catchment: str = "",
    trend: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> dict[str, Any]:
    """Persist an alert for human review. Nothing is transmitted here.

    Invariant 3: escalation requires an explicit Approve in the UI. This only
    creates the pending row.
    """
    conn, owned, config = _resolve(connection, config)
    try:
        trace_id = trace.record(
            "agent",
            "raise_alert",
            {
                "severity": severity,
                "syndrome": syndrome,
                "case_ids": case_ids,
                "window_hours": window_hours,
                "catchment": catchment,
            },
            connection=conn,
        )
        started = time.perf_counter()

        alert_id = f"alert-{uuid.uuid4().hex[:8]}"
        conn.execute(
            "INSERT INTO alerts (id, severity, syndrome_code, catchment,"
            " case_ids_json, window_hours, trend, rationale_text, status,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
            (
                alert_id,
                severity,
                syndrome,
                catchment,
                json.dumps(sorted(case_ids)),
                window_hours,
                trend,
                rationale_text,
                utcnow(),
            ),
        )

        trace.update(
            trace_id,
            result_summary=f"alert_id={alert_id} cases={len(case_ids)}",
            duration_ms=int((time.perf_counter() - started) * 1000),
            connection=conn,
        )
        return {"alert_id": alert_id}
    finally:
        if owned:
            conn.close()


# Exposed to the OpenClaw agent. Kept as data so the harness and the tests
# agree on exactly one list.
TOOL_NAMES = ("query_graph", "get_case_def", "score_film", "raise_alert")

TOOL_SPECS: dict[str, dict[str, Any]] = {
    "query_graph": {
        "description": (
            "Count cases matching a syndrome and catchment in a rolling window, "
            "with the preceding period as a baseline."
        ),
        "params": {
            "syndrome_code": "string|null",
            "catchment": "string|null",
            "window_hours": "integer",
        },
    },
    "get_case_def": {
        "description": "Retrieve the WHO syndromic case definition matching a query.",
        "params": {"query": "string"},
    },
    "score_film": {
        "description": "Return the stored chest-film abnormality score for a case.",
        "params": {"case_id": "string"},
    },
    "raise_alert": {
        "description": (
            "Record a pending cluster alert for human review. Does not transmit."
        ),
        "params": {
            "severity": "string",
            "syndrome": "string",
            "case_ids": "array of string",
            "window_hours": "integer",
            "rationale_text": "string",
        },
    },
}
