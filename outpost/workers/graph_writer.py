"""F-05 — write a processed case into the graph.

The graph is SQLite tables, not Neo4j (D2): ``nodes`` + ``edges``, plus the
denormalised ``cases`` table.

That denormalisation is the load-bearing part. ``cases`` is the **only** table
alert logic reads (ARCHITECTURE §3 invariant), which is what keeps free text
structurally incapable of manufacturing an outbreak — invariant 5. Traversing
the graph to find clusters would work, but it would also put ``artifacts`` one
join away from the alert path. Keeping the surveillance view separate makes the
invariant enforceable rather than merely intended.

Node ids are ``patient:<id>``, ``visit:<id>``, ``syndrome:<code>``. Edges are
``had_visit`` (patient → visit) and ``presented_as`` (visit → syndrome).
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect, utcnow


@dataclass(frozen=True)
class GraphWrite:
    """What one case contributed to the graph."""

    case_id: str
    patient_id: str
    visit_id: str
    syndrome_code: str
    catchment: str
    nodes_written: int
    edges_written: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "patient_id": self.patient_id,
            "syndrome_code": self.syndrome_code,
            "catchment": self.catchment,
        }


def patient_node_id(patient_id: str) -> str:
    return f"patient:{patient_id}"


def visit_node_id(visit_id: str) -> str:
    return f"visit:{visit_id}"


def syndrome_node_id(code: str) -> str:
    return f"syndrome:{code}"


def _upsert_node(
    conn: sqlite3.Connection,
    node_id: str,
    node_type: str,
    label: str | None = None,
    attrs: dict[str, Any] | None = None,
) -> bool:
    """Insert a node if absent. True when a new row was created."""
    existing = conn.execute(
        "SELECT 1 FROM nodes WHERE id = ?", (node_id,)
    ).fetchone()
    if existing:
        if label or attrs:
            conn.execute(
                "UPDATE nodes SET label = COALESCE(?, label),"
                " attrs_json = COALESCE(?, attrs_json) WHERE id = ?",
                (label, json.dumps(attrs) if attrs else None, node_id),
            )
        return False

    conn.execute(
        "INSERT INTO nodes (id, type, label, attrs_json, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (node_id, node_type, label, json.dumps(attrs or {}), utcnow()),
    )
    return True


def _upsert_edge(conn: sqlite3.Connection, src: str, dst: str, rel: str) -> bool:
    """Insert an edge if absent. True when a new row was created."""
    cursor = conn.execute(
        "INSERT OR IGNORE INTO edges (src, dst, rel, created_at) VALUES (?, ?, ?, ?)",
        (src, dst, rel, utcnow()),
    )
    return cursor.rowcount > 0


def write_case(
    case_id: str,
    patient_id: str,
    syndrome_code: str,
    catchment: str,
    *,
    occurred_at: str | None = None,
    film_score: int | None = None,
    patient_label: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> GraphWrite:
    """Write one case to the graph and the surveillance view. Idempotent."""
    config = config or settings
    occurred_at = occurred_at or utcnow()
    visit_id = case_id  # one visit per case for this build

    owned = connection is None
    conn = connection or connect(config)
    try:
        trace_id = trace.record(
            "worker:graph",
            "write_case",
            {
                "case_id": case_id,
                "patient_id": patient_id,
                "syndrome_code": syndrome_code,
                "catchment": catchment,
            },
            connection=conn,
        )
        started = time.perf_counter()

        nodes_written = 0
        nodes_written += _upsert_node(
            conn, patient_node_id(patient_id), "patient", patient_label
        )
        nodes_written += _upsert_node(
            conn,
            visit_node_id(visit_id),
            "visit",
            attrs={"catchment": catchment, "occurred_at": occurred_at},
        )
        nodes_written += _upsert_node(
            conn, syndrome_node_id(syndrome_code), "syndrome", syndrome_code
        )

        edges_written = 0
        edges_written += _upsert_edge(
            conn, patient_node_id(patient_id), visit_node_id(visit_id), "had_visit"
        )
        edges_written += _upsert_edge(
            conn,
            visit_node_id(visit_id),
            syndrome_node_id(syndrome_code),
            "presented_as",
        )

        # The denormalised surveillance view — the only table alert logic reads.
        conn.execute(
            "INSERT INTO cases (case_id, patient_id, syndrome_code, catchment,"
            " film_score, occurred_at) VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO UPDATE SET"
            " patient_id = excluded.patient_id,"
            " syndrome_code = excluded.syndrome_code,"
            " catchment = excluded.catchment,"
            " film_score = excluded.film_score,"
            " occurred_at = excluded.occurred_at",
            (case_id, patient_id, syndrome_code, catchment, film_score, occurred_at),
        )

        result = GraphWrite(
            case_id=case_id,
            patient_id=patient_id,
            visit_id=visit_id,
            syndrome_code=syndrome_code,
            catchment=catchment,
            nodes_written=nodes_written,
            edges_written=edges_written,
        )

        trace.update(
            trace_id,
            result_summary=(
                f"nodes+{nodes_written} edges+{edges_written} "
                f"syndrome={syndrome_code} catchment={catchment}"
            ),
            duration_ms=int((time.perf_counter() - started) * 1000),
            connection=conn,
        )
        return result
    finally:
        if owned:
            conn.close()


def write_from_artifacts(
    case_id: str,
    patient_id: str,
    catchment: str,
    *,
    occurred_at: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> GraphWrite | None:
    """Promote a processed case from ``artifacts`` into the graph.

    Only structured fields cross this boundary — syndrome code and film score.
    Free text stays in ``artifacts`` where alert logic cannot reach it.
    """
    config = config or settings

    owned = connection is None
    conn = connection or connect(config)
    try:
        row = conn.execute(
            "SELECT syndrome_code, film_score FROM artifacts WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        if row is None or not row["syndrome_code"]:
            return None

        return write_case(
            case_id,
            patient_id,
            row["syndrome_code"],
            catchment,
            occurred_at=occurred_at,
            film_score=row["film_score"],
            connection=conn,
            config=config,
        )
    finally:
        if owned:
            conn.close()


def case_count(
    connection: sqlite3.Connection | None = None, config: Settings | None = None
) -> int:
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0])
    finally:
        if owned:
            conn.close()
