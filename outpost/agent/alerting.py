"""F-07 — cluster detection and alert drafting.

Trigger (``docs/ARCHITECTURE.md`` §4): **≥3 cases, same ``syndrome_code``, same
``catchment``, rolling 72h window.** Fewer than 3 → no alert. Spread across
catchments → no alert. Thresholds are configurable because per-setting
calibration is WHO's stated requirement.

**Invariant 5 is enforced structurally here.** This module reads ``cases`` and
``case_definitions`` and nothing else. The threshold decision is arithmetic in
SQL — no model output participates in it. OpenClaw is asked only to phrase a
rationale *after* the numbers already decided, and its text is stored for a
human to read. If the model returns nothing, a deterministic template is used
and the alert is identical in every field that matters.

Safety language (AGENTS.md): alerts describe *signal*, never a conclusion.
"3 cases matching acute watery diarrhoea in sector-4 within 72h — review
recommended", never "cholera outbreak".
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from typing import Any

from outpost import trace
from outpost.agent import openclaw, tools
from outpost.config import Settings, settings
from outpost.db import connect, utcnow

SEVERITY_BY_RATIO = (
    (3.0, "high"),
    (1.5, "moderate"),
    (0.0, "low"),
)

NARRATION_CONTEXT = """You are a surveillance assistant in a field hospital.

Write ONE short paragraph (max 3 sentences) for a project medical lead,
describing a possible case cluster that has been detected by threshold counting.

Rules you must follow:
- Describe SIGNAL, not a conclusion. Never name a disease or declare an outbreak.
- Say "cases matching <syndrome>", never "confirmed" or "diagnosed".
- Recommend review or investigation. Do not recommend treatment.
- State that thresholds are calibrated per setting.
- Use only the figures given. Do not invent numbers.
- Reply with plain prose only. No JSON, no markdown, no preamble."""


@dataclass(frozen=True)
class Cluster:
    """A (syndrome, catchment) group that crossed the threshold."""

    syndrome_code: str
    catchment: str
    case_ids: list[str]
    count: int
    baseline_count: int
    window_hours: int

    @property
    def severity(self) -> str:
        """Severity from the rise over baseline, not the raw count."""
        if self.baseline_count <= 0:
            return "high" if self.count >= 5 else "moderate"
        ratio = self.count / self.baseline_count
        for threshold, label in SEVERITY_BY_RATIO:
            if ratio >= threshold:
                return label
        return "low"

    @property
    def trend(self) -> str:
        if self.count > self.baseline_count:
            return "rising"
        if self.count < self.baseline_count:
            return "falling"
        return "stable"

    def as_facts(self) -> dict[str, Any]:
        return {
            "syndrome": self.syndrome_code,
            "catchment": self.catchment,
            "case_count": self.count,
            "baseline_count_previous_window": self.baseline_count,
            "window_hours": self.window_hours,
            "trend": self.trend,
        }


def default_rationale(cluster: Cluster, title: str = "") -> str:
    """Deterministic rationale used when OpenClaw is unavailable.

    Deliberately says the same thing the model is asked to say, so a fallback
    alert is not visibly degraded.
    """
    label = title or cluster.syndrome_code.replace("_", " ")
    baseline = (
        f"against {cluster.baseline_count} in the preceding {cluster.window_hours}h"
        if cluster.baseline_count
        else f"with none recorded in the preceding {cluster.window_hours}h"
    )
    return (
        f"{cluster.count} cases matching {label} recorded in {cluster.catchment} "
        f"within {cluster.window_hours}h, {baseline}. This is a surveillance "
        f"signal for review, not an outbreak declaration. Thresholds are "
        f"calibrated per setting; investigation by the medical lead is recommended."
    )


def find_clusters(
    *,
    now: str | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> list[Cluster]:
    """Return every (syndrome, catchment) group over threshold.

    Reads ``cases`` only.
    """
    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        anchor = now or utcnow()
        groups = conn.execute(
            "SELECT syndrome_code, catchment, COUNT(*) AS n FROM cases"
            " WHERE datetime(occurred_at) > datetime(?, ?)"
            "   AND datetime(occurred_at) <= datetime(?)"
            "   AND syndrome_code != 'unmapped'"
            " GROUP BY syndrome_code, catchment"
            " HAVING n >= ?"
            " ORDER BY n DESC",
            [
                anchor,
                f"-{config.alert_window_hours} hours",
                anchor,
                config.alert_min_cases,
            ],
        ).fetchall()

        clusters: list[Cluster] = []
        for group in groups:
            detail = tools.query_graph(
                group["syndrome_code"],
                group["catchment"],
                config.alert_window_hours,
                now=anchor,
                connection=conn,
                config=config,
            )
            clusters.append(
                Cluster(
                    syndrome_code=group["syndrome_code"],
                    catchment=group["catchment"],
                    case_ids=[case["case_id"] for case in detail["cases"]],
                    count=detail["count"],
                    baseline_count=detail["baseline_count"],
                    window_hours=config.alert_window_hours,
                )
            )
        return clusters
    finally:
        if owned:
            conn.close()


def has_open_alert(
    syndrome_code: str,
    catchment: str,
    *,
    case_ids: list[str] | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> bool:
    """True when this group has already been alerted on and nothing is new.

    Two distinct suppressions, both necessary:

    * A **pending** alert blocks re-raising, or the 30s heartbeat would post a
      duplicate every cycle and bury the reviewer.
    * A **decided** alert blocks re-raising too, unless the cluster has grown.
      Approving an alert does not make the cases disappear, so without this the
      same cluster re-alerts 30 seconds after it was actioned. Alert fatigue is
      the classic way a surveillance system stops being read, and re-raising an
      alert a human just dealt with is exactly how it starts.

    Passing ``case_ids`` enables the growth check: a genuinely new case in the
    same group produces a new alert, which is the behaviour that matters.
    """
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        rows = conn.execute(
            "SELECT status, case_ids_json FROM alerts"
            " WHERE syndrome_code = ? AND catchment = ?",
            (syndrome_code, catchment),
        ).fetchall()
        if not rows:
            return False

        if any(row["status"] == "pending" for row in rows):
            return True

        if case_ids is None:
            return True

        # Already-reviewed cases across every decided alert for this group.
        reviewed: set[str] = set()
        for row in rows:
            reviewed.update(json.loads(row["case_ids_json"]))

        # Suppress only while there is nothing the reviewer has not already seen.
        return set(case_ids).issubset(reviewed)
    finally:
        if owned:
            conn.close()


def build_rationale(
    cluster: Cluster,
    *,
    use_agent: bool = True,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> str:
    """Phrase the rationale, preferring OpenClaw and falling back to a template."""
    config = config or settings

    title = ""
    if connection is not None:
        row = connection.execute(
            "SELECT title FROM case_definitions WHERE code = ?",
            (cluster.syndrome_code,),
        ).fetchone()
        title = row["title"] if row else ""

    if use_agent:
        reply = openclaw.narrate(
            NARRATION_CONTEXT,
            cluster.as_facts(),
            session_key=f"outpost-alert-{cluster.syndrome_code}",
            connection=connection,
            config=config,
        )
        if reply is not None and reply.text.strip():
            return reply.text.strip()

    return default_rationale(cluster, title)


def evaluate(
    *,
    now: str | None = None,
    use_agent: bool = True,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> list[str]:
    """Detect clusters and raise alerts. Returns new alert ids.

    Always writes the deterministic rationale first. Agent narration is
    deliberately **not** inline: measured OpenClaw turn time ranged from 20s to
    165s, which would blow the F-06 heartbeat budget and, worse, make it
    unpredictable. ``enrich_alert`` upgrades the text afterwards.
    """
    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        raised: list[str] = []
        for cluster in find_clusters(now=now, connection=conn, config=config):
            if has_open_alert(
                cluster.syndrome_code,
                cluster.catchment,
                case_ids=cluster.case_ids,
                connection=conn,
                config=config,
            ):
                continue

            rationale = build_rationale(
                cluster, use_agent=False, connection=conn, config=config
            )
            result = tools.raise_alert(
                cluster.severity,
                cluster.syndrome_code,
                cluster.case_ids,
                cluster.window_hours,
                rationale,
                catchment=cluster.catchment,
                trend=cluster.trend,
                connection=conn,
                config=config,
            )
            raised.append(result["alert_id"])

        if use_agent and raised:
            enrich_alerts_async(raised, config=config)

        return raised
    finally:
        if owned:
            conn.close()


def enrich_alert(
    alert_id: str,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> bool:
    """Replace an alert's template rationale with an OpenClaw narration.

    Only the wording changes. Severity, case ids, counts and the egress payload
    are all decided by arithmetic and are untouched here — invariant 5 holds
    whether or not this ever runs.
    """
    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        row = conn.execute(
            "SELECT * FROM alerts WHERE id = ? AND rationale_source = 'template'",
            (alert_id,),
        ).fetchone()
        if row is None:
            return False

        cluster = Cluster(
            syndrome_code=row["syndrome_code"],
            catchment=row["catchment"],
            case_ids=json.loads(row["case_ids_json"]),
            count=len(json.loads(row["case_ids_json"])),
            baseline_count=0,
            window_hours=row["window_hours"],
        )
        reply = openclaw.narrate(
            NARRATION_CONTEXT,
            cluster.as_facts(),
            session_key=f"outpost-alert-{alert_id}",
            connection=conn,
            config=config,
        )
        if reply is None or not reply.text.strip():
            return False

        conn.execute(
            "UPDATE alerts SET rationale_text = ?, rationale_source = 'agent'"
            " WHERE id = ? AND status = 'pending'",
            (reply.text.strip(), alert_id),
        )
        return True
    finally:
        if owned:
            conn.close()


def enrich_alerts_async(
    alert_ids: list[str], *, config: Settings | None = None
) -> threading.Thread:
    """Upgrade rationales off the heartbeat thread.

    Daemon so it can never hold the process open, and every failure is
    swallowed into the trace — the alert is already correct without it.
    """
    config = config or settings

    def _worker() -> None:
        for alert_id in alert_ids:
            try:
                enrich_alert(alert_id, config=config)
            except Exception as exc:
                trace.record(
                    "agent",
                    "enrich_alert",
                    {"alert_id": alert_id},
                    result_summary=f"ERROR {type(exc).__name__}: {exc}",
                    config=config,
                )

    thread = threading.Thread(
        target=_worker, name="outpost-enrich", daemon=True
    )
    thread.start()
    return thread


def pending_alerts(
    connection: sqlite3.Connection | None = None, config: Settings | None = None
) -> list[dict[str, Any]]:
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        rows = conn.execute(
            "SELECT * FROM alerts WHERE status = 'pending' ORDER BY created_at DESC"
        ).fetchall()
        return [
            {**dict(row), "case_ids": json.loads(row["case_ids_json"])} for row in rows
        ]
    finally:
        if owned:
            conn.close()
