"""F-10 — the only thing that ever leaves the box.

Contract (``docs/ARCHITECTURE.md`` §6): exactly one allowlisted host, counts
only, under 1KB.

``EgressPayload`` is a frozen dataclass with **exactly six fields**. No
``**kwargs``, no passthrough dict, no debug fields. That is the whole point: a
dict would let a future edit add ``case_id`` in one line and nobody would
notice. The type makes the privacy guarantee structural rather than a
convention someone has to remember.

Invariant 3: this runs from the Approve handler and nowhere else. Invariant 2:
no names, no ages, no free text, no identifiers.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect, utcnow

MAX_PAYLOAD_BYTES = 1024

# Field names that must never appear in an outbound payload. Asserted in tests
# and re-checked at runtime — this is cheap and the failure mode is severe.
FORBIDDEN_KEYS = (
    "case_id",
    "case_ids",
    "patient",
    "patient_id",
    "name",
    "age",
    "sex",
    "dob",
    "transcript",
    "native_transcript",
    "english_text",
    "findings",
    "film_findings",
    "rationale",
    "rationale_text",
    "notes",
)


class EgressBlocked(RuntimeError):
    """The payload failed its own contract, or the endpoint refused it."""


@dataclass(frozen=True)
class EgressPayload:
    """The complete set of fields that may cross the wire.

    Adding a field here is a deliberate act that shows up in review. That is
    the design.
    """

    syndrome: str
    catchment: str
    count: int
    window_hours: int
    trend: str
    site_id: str

    def to_json(self) -> str:
        # sort_keys keeps the byte count stable so the number shown on camera
        # is reproducible.
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)

    def byte_size(self) -> int:
        return len(self.to_json().encode("utf-8"))

    def validate(self) -> None:
        """Re-check the contract immediately before sending."""
        encoded = self.to_json()
        size = len(encoded.encode("utf-8"))
        if size >= MAX_PAYLOAD_BYTES:
            raise EgressBlocked(f"payload is {size} bytes, limit is {MAX_PAYLOAD_BYTES}")

        parsed = json.loads(encoded)
        if set(parsed) != {
            "syndrome", "catchment", "count", "window_hours", "trend", "site_id"
        }:
            raise EgressBlocked(f"unexpected fields in payload: {sorted(parsed)}")

        lowered = encoded.lower()
        for key in FORBIDDEN_KEYS:
            if f'"{key}"' in lowered:
                raise EgressBlocked(f"payload contains forbidden key {key!r}")


def payload_for_alert(
    alert: dict[str, Any], *, config: Settings | None = None
) -> EgressPayload:
    """Build the aggregate payload for an alert.

    Only counts survive: the case ids are collapsed to their length and the
    rationale is dropped entirely.
    """
    config = config or settings
    case_ids = alert.get("case_ids")
    if case_ids is None:
        case_ids = json.loads(alert.get("case_ids_json") or "[]")

    return EgressPayload(
        syndrome=str(alert["syndrome_code"]),
        catchment=str(alert["catchment"]),
        count=len(case_ids),
        window_hours=int(alert["window_hours"]),
        trend=str(alert.get("trend") or "stable"),
        site_id=config.site_id,
    )


def send(
    payload: EgressPayload,
    *,
    url: str | None = None,
    config: Settings | None = None,
    connection: sqlite3.Connection | None = None,
) -> int:
    """POST to the single allowlisted endpoint. Returns bytes sent."""
    config = config or settings
    target = url or config.egress_url

    payload.validate()
    body = payload.to_json()
    size = len(body.encode("utf-8"))

    trace_id = trace.record(
        "egress",
        "send",
        {"url": target, "bytes": size, "payload": json.loads(body)},
        connection=connection,
        config=config,
    )

    try:
        response = httpx.post(
            target,
            content=body,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        trace.update(
            trace_id,
            result_summary=f"ERROR {type(exc).__name__}: {exc}",
            duration_ms=0,
            connection=connection,
            config=config,
        )
        raise EgressBlocked(f"egress to {target} failed: {exc}") from exc

    trace.update(
        trace_id,
        result_summary=f"sent {size} bytes to {target} ({response.status_code})",
        duration_ms=0,
        connection=connection,
        config=config,
    )
    return size


def approve_alert(
    alert_id: str,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> int:
    """Approve an alert and transmit its aggregate payload.

    **This is the only call site of ``send``.** Invariant 3: nothing is
    transmitted without an explicit human Approve.
    """
    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        row = conn.execute(
            "SELECT * FROM alerts WHERE id = ? AND status = 'pending'", (alert_id,)
        ).fetchone()
        if row is None:
            raise EgressBlocked(f"no pending alert {alert_id!r}")

        payload = payload_for_alert(dict(row), config=config)
        size = send(payload, config=config, connection=conn)

        conn.execute(
            "UPDATE alerts SET status = 'approved', bytes_sent = ?, decided_at = ?"
            " WHERE id = ?",
            (size, utcnow(), alert_id),
        )
        return size
    finally:
        if owned:
            conn.close()


def dismiss_alert(
    alert_id: str,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> bool:
    """Dismiss an alert. Nothing is transmitted."""
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        cursor = conn.execute(
            "UPDATE alerts SET status = 'dismissed', decided_at = ?"
            " WHERE id = ? AND status = 'pending'",
            (utcnow(), alert_id),
        )
        return cursor.rowcount > 0
    finally:
        if owned:
            conn.close()


def bytes_on_box(
    connection: sqlite3.Connection | None = None, config: Settings | None = None
) -> int:
    """Bytes of clinical data held locally — the counterweight to bytes_sent.

    The comparison is the pitch: gigabytes stay, a few hundred bytes leave.
    """
    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        total = 0
        row = conn.execute(
            "SELECT COALESCE(SUM("
            " LENGTH(COALESCE(native_transcript,'')) +"
            " LENGTH(COALESCE(english_text,'')) +"
            " LENGTH(COALESCE(film_findings,''))), 0) FROM artifacts"
        ).fetchone()
        total += int(row[0])

        for directory in (config.artifacts_dir, config.inbox_dir):
            if directory.exists():
                total += sum(
                    path.stat().st_size
                    for path in directory.rglob("*")
                    if path.is_file()
                )
        if config.db_path.exists():
            total += config.db_path.stat().st_size
        return total
    finally:
        if owned:
            conn.close()


def bytes_sent(
    connection: sqlite3.Connection | None = None, config: Settings | None = None
) -> int:
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        return int(
            conn.execute(
                "SELECT COALESCE(SUM(bytes_sent), 0) FROM alerts"
            ).fetchone()[0]
        )
    finally:
        if owned:
            conn.close()
