"""Step 3 gate: the trace log records every tool call, including failures."""

from __future__ import annotations

import json
import sqlite3

import pytest

from outpost import trace
from outpost.config import Settings


def _rows(db: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM trace ORDER BY id").fetchall()]


def test_record_writes_one_row(db: sqlite3.Connection) -> None:
    trace.record("worker:vision", "score_film", {"case_id": "case-1"}, connection=db)
    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["actor"] == "worker:vision"
    assert rows[0]["tool"] == "score_film"
    assert json.loads(rows[0]["args_json"]) == {"case_id": "case-1"}
    assert rows[0]["ts"].endswith("+00:00")


def test_traced_decorator_records_success(
    db: sqlite3.Connection, test_settings: Settings, monkeypatch
) -> None:
    monkeypatch.setattr(trace, "settings", test_settings)

    @trace.traced("agent", "query_graph")
    def query(count: int) -> dict:
        return {"count": count, "cases": []}

    assert query(3) == {"count": 3, "cases": []}

    rows = _rows(db)
    assert len(rows) == 1, "exactly one row per call"
    assert rows[0]["tool"] == "query_graph"
    assert "count=3" in rows[0]["result_summary"]
    assert rows[0]["duration_ms"] is not None


def test_traced_decorator_records_failure(
    db: sqlite3.Connection, test_settings: Settings, monkeypatch
) -> None:
    """A tool that blew up is exactly what a judge needs to see."""
    monkeypatch.setattr(trace, "settings", test_settings)

    @trace.traced("worker:asr")
    def explode() -> None:
        raise ValueError("model unavailable")

    with pytest.raises(ValueError, match="model unavailable"):
        explode()

    rows = _rows(db)
    assert len(rows) == 1
    assert rows[0]["tool"] == "explode"
    assert "ERROR ValueError" in rows[0]["result_summary"]
    assert "model unavailable" in rows[0]["result_summary"]
    assert rows[0]["duration_ms"] is not None


def test_cycle_id_is_attached(
    db: sqlite3.Connection, test_settings: Settings, monkeypatch
) -> None:
    """One heartbeat pass groups its tool calls under a single cycle."""
    monkeypatch.setattr(trace, "settings", test_settings)
    cycle = trace.new_cycle_id()
    trace.set_cycle(cycle)
    try:

        @trace.traced("agent")
        def step() -> str:
            return "done"

        step()
        step()
    finally:
        trace.set_cycle(None)

    trace.record("agent", "outside", {}, connection=db)

    rows = _rows(db)
    assert [r["cycle_id"] for r in rows] == [cycle, cycle, None]
    assert cycle.startswith("cycle-")


def test_args_are_truncated_not_dropped(db: sqlite3.Connection) -> None:
    trace.record("agent", "big", {"blob": "x" * 10_000}, connection=db)
    stored = _rows(db)[0]["args_json"]
    assert len(stored) <= trace.MAX_ARGS_CHARS + 40
    assert "chars)" in stored


def test_non_serialisable_args_do_not_raise(db: sqlite3.Connection) -> None:
    """The trace must never be the thing that breaks the demo path."""

    class Opaque:
        pass

    trace.record("agent", "weird", {"obj": Opaque(), "path": object()}, connection=db)
    assert len(_rows(db)) == 1


def test_recent_returns_newest_first(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    for index in range(5):
        trace.record("agent", f"tool-{index}", {}, connection=db)

    rows = trace.recent(limit=3, connection=db)
    assert [row["tool"] for row in rows] == ["tool-4", "tool-3", "tool-2"]


def test_recent_filters_by_cycle(db: sqlite3.Connection) -> None:
    trace.record("agent", "a", {}, cycle_id="cycle-aaa", connection=db)
    trace.record("agent", "b", {}, cycle_id="cycle-bbb", connection=db)
    trace.record("agent", "c", {}, cycle_id="cycle-aaa", connection=db)

    rows = trace.recent(cycle_id="cycle-aaa", connection=db)
    assert [row["tool"] for row in rows] == ["c", "a"]
