"""Tool-call audit log — this table *is* the trace panel.

AGENTS.md invariant 8: every agent tool call is logged with timestamp and
arguments. Visible reasoning is 30% of the score (D8), so tracing is not
diagnostics you can strip out — it is a product surface.

Two rules that drive the design:

* A call is recorded even when it raises. A tool that blew up is exactly the
  thing a judge needs to see, and AGENTS.md forbids silently swallowing
  exceptions on the demo path.
* Arguments are truncated, never dropped. The panel has to stay readable.
"""

from __future__ import annotations

import functools
import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from typing import Any, ParamSpec, TypeVar

from outpost.config import Settings, settings
from outpost.db import connect, utcnow

P = ParamSpec("P")
R = TypeVar("R")

MAX_ARGS_CHARS = 2000
MAX_SUMMARY_CHARS = 500

# Set by the heartbeat so every tool call in one pass shares a cycle id.
_current_cycle: ContextVar[str | None] = ContextVar("outpost_cycle_id", default=None)


def new_cycle_id() -> str:
    return f"cycle-{uuid.uuid4().hex[:8]}"


def set_cycle(cycle_id: str | None) -> None:
    _current_cycle.set(cycle_id)


def current_cycle() -> str | None:
    return _current_cycle.get()


def _json_safe(value: Any) -> Any:
    """Coerce anything into something json.dumps will accept."""
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_safe(item) for item in value]
    return repr(value)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}… (+{len(text) - limit} chars)"


def _summarise(result: Any) -> str:
    """One readable line for the trace panel."""
    if result is None:
        return "ok"
    if isinstance(result, dict):
        if "count" in result:
            return _truncate(
                f"count={result['count']} keys={sorted(result)}", MAX_SUMMARY_CHARS
            )
        return _truncate(f"keys={sorted(result)}", MAX_SUMMARY_CHARS)
    if isinstance(result, list | tuple):
        return f"{len(result)} items"
    return _truncate(str(result), MAX_SUMMARY_CHARS)


def record(
    actor: str,
    tool: str,
    args: Any,
    *,
    result_summary: str | None = None,
    duration_ms: int | None = None,
    cycle_id: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> int:
    """Append one trace row. Returns its id."""
    payload = _truncate(
        json.dumps(_json_safe(args), ensure_ascii=False, default=repr), MAX_ARGS_CHARS
    )
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        cursor = conn.execute(
            "INSERT INTO trace (ts, cycle_id, actor, tool, args_json,"
            " result_summary, duration_ms) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                utcnow(),
                cycle_id if cycle_id is not None else current_cycle(),
                actor,
                tool,
                payload,
                result_summary,
                duration_ms,
            ),
        )
        return int(cursor.lastrowid or 0)
    finally:
        if owned:
            conn.close()


def update(
    trace_id: int,
    *,
    result_summary: str,
    duration_ms: int,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> None:
    """Complete a previously opened trace row."""
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        conn.execute(
            "UPDATE trace SET result_summary = ?, duration_ms = ? WHERE id = ?",
            (_truncate(result_summary, MAX_SUMMARY_CHARS), duration_ms, trace_id),
        )
    finally:
        if owned:
            conn.close()


def traced(actor: str, tool: str | None = None) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Log a call before it runs and complete the row after.

    The row is written *before* execution so a hung or crashed tool still
    appears in the panel — an empty trace during a stall is the worst possible
    demo outcome.
    """

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        tool_name = tool or func.__name__

        @functools.wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            trace_id = record(actor, tool_name, {"args": args, "kwargs": kwargs})
            started = time.perf_counter()
            try:
                result = func(*args, **kwargs)
            except Exception as exc:
                update(
                    trace_id,
                    result_summary=f"ERROR {type(exc).__name__}: {exc}",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                raise
            update(
                trace_id,
                result_summary=_summarise(result),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            return result

        return wrapper

    return decorator


def recent(
    limit: int = 100,
    *,
    cycle_id: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> list[dict[str, Any]]:
    """Most recent calls, newest first — the trace panel's data source."""
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        if cycle_id:
            rows = conn.execute(
                "SELECT * FROM trace WHERE cycle_id = ? ORDER BY id DESC LIMIT ?",
                (cycle_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM trace ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        if owned:
            conn.close()
