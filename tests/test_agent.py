"""Steps 9-10 gates: agent tools (ARCHITECTURE §4) and F-07 alert logic."""

from __future__ import annotations

import inspect
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from outpost.agent import alerting, openclaw, tools
from outpost.config import Settings

ANCHOR = datetime(2026, 7, 26, 12, 0, 0, tzinfo=UTC)


def iso(hours_ago: float) -> str:
    return (ANCHOR - timedelta(hours=hours_ago)).isoformat(timespec="seconds")


def add_case(
    db: sqlite3.Connection,
    case_id: str,
    *,
    hours_ago: float,
    syndrome: str = "acute_watery_diarrhoea",
    catchment: str = "sector-4",
    patient: str | None = None,
    film_score: int | None = None,
) -> None:
    db.execute(
        "INSERT INTO cases (case_id, patient_id, syndrome_code, catchment,"
        " film_score, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
        (case_id, patient or f"p-{case_id}", syndrome, catchment, film_score,
         iso(hours_ago)),
    )


class TestQueryGraph:
    def test_returns_architecture_keys(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        result = tools.query_graph(
            "acute_watery_diarrhoea", "sector-4", 72,
            now=ANCHOR.isoformat(), connection=db, config=test_settings,
        )
        assert set(result) == {"count", "cases", "baseline_count"}

    def test_counts_only_inside_the_window(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """The bug this guards: ISO 'T' sorts above ' ', so naive string
        comparison silently counted a 73h-old case inside a 72h window."""
        add_case(db, "inside-1", hours_ago=1)
        add_case(db, "inside-71", hours_ago=71)
        add_case(db, "outside-73", hours_ago=73)
        add_case(db, "outside-200", hours_ago=200)

        result = tools.query_graph(
            "acute_watery_diarrhoea", "sector-4", 72,
            now=ANCHOR.isoformat(), connection=db, config=test_settings,
        )
        assert result["count"] == 2
        assert {c["case_id"] for c in result["cases"]} == {"inside-1", "inside-71"}

    def test_baseline_is_the_preceding_window(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for hours in (1, 2, 3):
            add_case(db, f"now-{hours}", hours_ago=hours)
        for hours in (80, 100):
            add_case(db, f"prev-{hours}", hours_ago=hours)
        add_case(db, "ancient", hours_ago=200)  # outside both windows

        result = tools.query_graph(
            "acute_watery_diarrhoea", "sector-4", 72,
            now=ANCHOR.isoformat(), connection=db, config=test_settings,
        )
        assert result["count"] == 3
        assert result["baseline_count"] == 2

    def test_filters_by_catchment(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        add_case(db, "a", hours_ago=1, catchment="sector-4")
        add_case(db, "b", hours_ago=1, catchment="sector-9")

        result = tools.query_graph(
            "acute_watery_diarrhoea", "sector-4", 72,
            now=ANCHOR.isoformat(), connection=db, config=test_settings,
        )
        assert result["count"] == 1

    def test_no_filters_counts_everything(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        add_case(db, "a", hours_ago=1, syndrome="acute_febrile_illness")
        add_case(db, "b", hours_ago=1, catchment="sector-9")

        result = tools.query_graph(
            None, None, 72, now=ANCHOR.isoformat(), connection=db, config=test_settings
        )
        assert result["count"] == 2

    def test_is_traced(self, db: sqlite3.Connection, test_settings: Settings) -> None:
        tools.query_graph(
            None, None, 72, now=ANCHOR.isoformat(), connection=db, config=test_settings
        )
        rows = db.execute(
            "SELECT tool FROM trace WHERE actor='agent' AND tool='query_graph'"
        ).fetchall()
        assert len(rows) == 1


class TestOtherTools:
    def test_score_film_returns_spec_keys(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        db.execute(
            "INSERT INTO artifacts (case_id, film_score, film_findings, created_at)"
            " VALUES ('case-1', 88, 'patchy opacity', datetime('now'))"
        )
        result = tools.score_film("case-1", connection=db, config=test_settings)
        assert set(result) == {"case_id", "score", "findings"}
        assert result["score"] == 88

    def test_score_film_missing_case_is_safe(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        result = tools.score_film("absent", connection=db, config=test_settings)
        assert result["score"] is None
        assert result["findings"] == ""

    def test_raise_alert_creates_pending_row(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        result = tools.raise_alert(
            "high", "acute_watery_diarrhoea", ["c2", "c1"], 72, "because",
            catchment="sector-4", connection=db, config=test_settings,
        )
        assert set(result) == {"alert_id"}

        row = db.execute("SELECT * FROM alerts").fetchone()
        assert row["status"] == "pending", "invariant 3: nothing transmits here"
        assert row["case_ids_json"] == '["c1", "c2"]'

    def test_tool_names_match_architecture(self) -> None:
        assert tools.TOOL_NAMES == (
            "query_graph", "get_case_def", "score_film", "raise_alert"
        )
        assert set(tools.TOOL_SPECS) == set(tools.TOOL_NAMES)


class TestInvariantFive:
    """Alerts fire on structured fields only — never on free text."""

    def test_alerting_never_reads_narrative_columns(self) -> None:
        source = Path(alerting.__file__).read_text()
        for column in ("english_text", "native_transcript", "film_findings"):
            assert column not in source, (
                f"alerting.py references {column}; a hallucinated clause must "
                "not be able to manufacture an outbreak"
            )

    def test_alerting_only_queries_permitted_tables(self) -> None:
        source = Path(alerting.__file__).read_text().lower()
        assert "from artifacts" not in source
        assert "join artifacts" not in source

    def test_cluster_facts_carry_no_free_text(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        cluster = alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        )[0]

        facts = cluster.as_facts()
        assert set(facts) == {
            "syndrome", "catchment", "case_count",
            "baseline_count_previous_window", "window_hours", "trend",
        }
        for value in facts.values():
            assert not isinstance(value, str) or len(value) < 60


class TestClusterThresholds:
    """F-07: >=3 same syndrome, same catchment, rolling 72h."""

    def test_three_cases_fire(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        clusters = alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        )
        assert len(clusters) == 1
        assert clusters[0].count == 3

    def test_two_cases_do_not_fire(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index in range(2):
            add_case(db, f"c{index}", hours_ago=index + 1)
        assert alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        ) == []

    def test_spread_across_catchments_does_not_fire(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """The negative case worth demoing — it shows thresholds are real."""
        for index, sector in enumerate(["sector-1", "sector-2", "sector-3"]):
            add_case(db, f"c{index}", hours_ago=index + 1, catchment=sector)
        assert alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        ) == []

    def test_spread_across_syndromes_does_not_fire(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index, syndrome in enumerate(
            ["acute_watery_diarrhoea", "acute_febrile_illness", "suspected_measles"]
        ):
            add_case(db, f"c{index}", hours_ago=index + 1, syndrome=syndrome)
        assert alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        ) == []

    def test_cases_outside_window_do_not_count(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        add_case(db, "c0", hours_ago=1)
        add_case(db, "c1", hours_ago=2)
        add_case(db, "c2", hours_ago=80)
        assert alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        ) == []

    def test_unmapped_cases_are_excluded(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """An unmapped syndrome must never form a cluster."""
        for index in range(4):
            add_case(db, f"c{index}", hours_ago=index + 1, syndrome="unmapped")
        assert alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=test_settings
        ) == []

    def test_threshold_is_configurable(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """WHO requires per-setting calibration."""
        from dataclasses import replace

        for index in range(2):
            add_case(db, f"c{index}", hours_ago=index + 1)

        relaxed = replace(test_settings, alert_min_cases=2)
        assert len(alerting.find_clusters(
            now=ANCHOR.isoformat(), connection=db, config=relaxed
        )) == 1


class TestSeverityAndTrend:
    @pytest.mark.parametrize(
        ("count", "baseline", "expected"),
        [(9, 3, "high"), (5, 3, "moderate"), (3, 3, "low"), (6, 0, "high"), (3, 0, "moderate")],
    )
    def test_severity_from_rise_over_baseline(
        self, count: int, baseline: int, expected: str
    ) -> None:
        cluster = alerting.Cluster(
            "awd", "sector-4", [f"c{i}" for i in range(count)], count, baseline, 72
        )
        assert cluster.severity == expected

    @pytest.mark.parametrize(
        ("count", "baseline", "expected"),
        [(5, 2, "rising"), (2, 5, "falling"), (3, 3, "stable")],
    )
    def test_trend(self, count: int, baseline: int, expected: str) -> None:
        cluster = alerting.Cluster("awd", "sector-4", [], count, baseline, 72)
        assert cluster.trend == expected


class TestAlertRaising:
    def test_evaluate_raises_one_alert(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)

        raised = alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )
        assert len(raised) == 1

        row = db.execute("SELECT * FROM alerts").fetchone()
        assert row["status"] == "pending"
        assert row["syndrome_code"] == "acute_watery_diarrhoea"
        assert row["catchment"] == "sector-4"

    def test_repeat_evaluation_does_not_duplicate(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """The 30s heartbeat must not bury the reviewer in duplicates."""
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)

        for _ in range(4):
            alerting.evaluate(
                now=ANCHOR.isoformat(), use_agent=False,
                connection=db, config=test_settings,
            )

        assert db.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 1

    def test_new_alert_after_previous_is_decided(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )
        db.execute("UPDATE alerts SET status = 'dismissed'")

        raised = alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )
        assert len(raised) == 1

    def test_pending_alerts_parses_case_ids(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )
        alerts = alerting.pending_alerts(connection=db, config=test_settings)
        assert len(alerts) == 1
        assert sorted(alerts[0]["case_ids"]) == ["c0", "c1", "c2"]


class TestAsyncNarration:
    """Measured OpenClaw turn time ranged 20s-165s, so it cannot be inline."""

    def test_evaluate_does_not_block_on_the_agent(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        called = []
        monkeypatch.setattr(
            openclaw, "narrate", lambda *a, **k: called.append(1) or None
        )
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)

        alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )
        assert called == [], "narration must not run on the heartbeat thread"

    def test_alert_is_usable_before_enrichment(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """The template alert must be complete on its own."""
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )

        row = db.execute("SELECT * FROM alerts").fetchone()
        assert row["rationale_source"] == "template"
        assert row["severity"]
        assert row["rationale_text"]
        assert "cases matching" in row["rationale_text"].lower()

    def test_enrich_replaces_text_and_marks_source(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alert_id = alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )[0]

        monkeypatch.setattr(
            openclaw,
            "narrate",
            lambda *a, **k: openclaw.AgentReply("narrated text", "s", 10),
        )
        assert alerting.enrich_alert(
            alert_id, connection=db, config=test_settings
        ) is True

        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["rationale_text"] == "narrated text"
        assert row["rationale_source"] == "agent"

    def test_enrich_does_not_change_decision_fields(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        """Invariant 5: the model may reword, never re-decide."""
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alert_id = alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )[0]
        before = dict(
            db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        )

        monkeypatch.setattr(
            openclaw,
            "narrate",
            lambda *a, **k: openclaw.AgentReply("totally different", "s", 10),
        )
        alerting.enrich_alert(alert_id, connection=db, config=test_settings)
        after = dict(
            db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        )

        for field in (
            "severity", "syndrome_code", "catchment", "case_ids_json",
            "window_hours", "trend", "status",
        ):
            assert before[field] == after[field], f"{field} must not change"

    def test_enrich_is_idempotent(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alert_id = alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )[0]
        monkeypatch.setattr(
            openclaw, "narrate", lambda *a, **k: openclaw.AgentReply("once", "s", 10)
        )
        assert alerting.enrich_alert(alert_id, connection=db, config=test_settings)
        assert not alerting.enrich_alert(alert_id, connection=db, config=test_settings)

    def test_enrich_failure_leaves_alert_intact(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        for index in range(3):
            add_case(db, f"c{index}", hours_ago=index + 1)
        alert_id = alerting.evaluate(
            now=ANCHOR.isoformat(), use_agent=False, connection=db, config=test_settings
        )[0]
        original = db.execute(
            "SELECT rationale_text FROM alerts WHERE id = ?", (alert_id,)
        ).fetchone()["rationale_text"]

        monkeypatch.setattr(openclaw, "narrate", lambda *a, **k: None)
        assert not alerting.enrich_alert(alert_id, connection=db, config=test_settings)

        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["rationale_text"] == original
        assert row["rationale_source"] == "template"


class TestSafetyLanguage:
    """AGENTS.md: describe signal, never a conclusion."""

    def test_default_rationale_avoids_diagnosis(self) -> None:
        cluster = alerting.Cluster(
            "acute_watery_diarrhoea", "sector-4", ["c1", "c2", "c3"], 3, 0, 72
        )
        text = alerting.default_rationale(cluster).lower()

        assert "cases matching" in text
        assert "review" in text
        assert "calibrated per setting" in text
        for forbidden in ("cholera", "diagnos", "confirmed", "outbreak declared"):
            assert forbidden not in text

    def test_narration_prompt_forbids_naming_a_disease(self) -> None:
        prompt = alerting.NARRATION_CONTEXT.lower()
        assert "never name a disease" in prompt
        assert "signal, not a conclusion" in prompt
        assert "do not invent numbers" in prompt

    def test_rationale_falls_back_when_agent_unavailable(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        """A missing agent must not degrade the alert's substance."""
        monkeypatch.setattr(openclaw, "narrate", lambda *a, **k: None)
        cluster = alerting.Cluster(
            "acute_watery_diarrhoea", "sector-4", ["c1", "c2", "c3"], 3, 1, 72
        )
        text = alerting.build_rationale(
            cluster, use_agent=True, connection=db, config=test_settings
        )
        assert "cases matching" in text.lower()


class TestOpenClawHarness:
    def test_strips_ansi_and_diagnostics(self) -> None:
        raw = (
            "\x1b[33m[provider-transport-fetch]\x1b[39m \x1b[36m[model-fetch] "
            "start provider=ollama\x1b[39m\n"
            "OUTPOST-OK\n"
            "\x1b[33m[agents/agent-command]\x1b[39m run ended\n"
        )
        assert openclaw.clean_output(raw) == "OUTPOST-OK"

    def test_clean_output_handles_empty(self) -> None:
        assert openclaw.clean_output("") == ""
        assert openclaw.clean_output("[diagnostic] only noise") == ""

    def test_narrate_returns_none_when_unavailable(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        """The heartbeat must never stall on the agent."""
        monkeypatch.setattr(openclaw, "is_available", lambda: False)
        assert openclaw.narrate(
            "ctx", {"a": 1}, connection=db, config=test_settings
        ) is None

    def test_runs_locally_via_cli(self) -> None:
        """Invariant 1: the agent path shells to the local CLI, not an SDK."""
        source = inspect.getsource(openclaw.run_turn)
        assert '"--local"' in source
        assert '"openclaw"' in source


@pytest.mark.live
def test_live_openclaw_turn() -> None:
    """Real OpenClaw turn against local Ollama."""
    if not openclaw.is_available():
        pytest.skip("openclaw CLI not on PATH")

    reply = openclaw.run_turn(
        "Reply with exactly: OUTPOST-OK", session_key="outpost-pytest"
    )
    assert "OUTPOST-OK" in reply.text
    assert reply.duration_ms > 0
