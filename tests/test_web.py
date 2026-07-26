"""Step 13 gates (F-08, F-09, F-10, F-11): the web UI actually works."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from outpost import egress, trace
from outpost.agent import alerting, heartbeat
from outpost.config import Settings
from outpost.db import init_db, utcnow


@pytest.fixture
def client(db: sqlite3.Connection, test_settings: Settings, monkeypatch):
    """A client bound to the isolated temp database."""
    import outpost.web.app as web

    init_db(test_settings)
    monkeypatch.setattr(web, "settings", test_settings)
    monkeypatch.setattr(egress, "settings", test_settings)
    monkeypatch.setattr(alerting, "settings", test_settings)
    monkeypatch.setattr(heartbeat, "settings", test_settings)
    monkeypatch.setattr(trace, "settings", test_settings)
    return TestClient(web.app)


def seed_alert(db: sqlite3.Connection, alert_id: str = "alert-ui") -> str:
    db.execute(
        "INSERT INTO alerts (id, severity, syndrome_code, catchment, case_ids_json,"
        " window_hours, trend, rationale_text, created_at)"
        " VALUES (?, 'high', 'acute_watery_diarrhoea', 'sector-4', ?, 72, 'rising',"
        " ?, ?)",
        (
            alert_id,
            json.dumps(["case-0421", "case-0422", "case-0423"]),
            "3 cases matching acute watery diarrhoea in sector-4 within 72h — "
            "review recommended.",
            utcnow(),
        ),
    )
    return alert_id


def seed_case(db: sqlite3.Connection, case_id: str = "case-0421") -> None:
    occurred = (datetime.now(UTC) - timedelta(hours=2)).isoformat(timespec="seconds")
    db.execute(
        "INSERT INTO cases (case_id, patient_id, syndrome_code, catchment,"
        " film_score, occurred_at) VALUES (?, 'p-1', 'acute_watery_diarrhoea',"
        " 'sector-4', 73, ?)",
        (case_id, occurred),
    )
    db.execute(
        "INSERT INTO artifacts (case_id, native_transcript, english_text,"
        " source_language, film_score, film_findings, image_path, created_at)"
        " VALUES (?, ?, ?, 'fr', 73, 'patchy opacity right base', '/x/f.png', ?)",
        (
            case_id,
            "le patient rapporte des selles liquides abondantes",
            "the patient reports profuse watery stools",
            utcnow(),
        ),
    )


class TestRoutesRespond:
    @pytest.mark.parametrize(
        "path", ["/", "/api/status", "/api/trace", "/case/case-0421"]
    )
    def test_route_returns_200(self, client: TestClient, path: str) -> None:
        assert client.get(path).status_code == 200

    def test_dashboard_is_html(self, client: TestClient) -> None:
        response = client.get("/")
        assert "text/html" in response.headers["content-type"]
        assert "<!doctype html>" in response.text.lower()

    def test_empty_state_is_not_an_error(self, client: TestClient) -> None:
        """A fresh box must render, not 500."""
        html = client.get("/").text
        assert "No alerts" in html
        assert "Inbox empty" in html


class TestNoExternalAssets:
    """No CDN, no webfonts. The venue has no Wi-Fi (D4, working conventions)."""

    def test_dashboard_references_no_remote_assets(self, client: TestClient) -> None:
        html = client.get("/").text
        for marker in ("http://", "https://", "//cdn", "googleapis", "unpkg", "jsdelivr"):
            if marker in ("http://", "https://"):
                # The egress destination is rendered as text, which is fine;
                # what matters is that nothing is *loaded* from the network.
                continue
            assert marker not in html

    def test_no_script_or_link_tags_with_src(self, client: TestClient) -> None:
        import re

        html = client.get("/").text
        remote = re.findall(r'<(?:script|link)[^>]*(?:src|href)="(https?://[^"]+)"', html)
        assert remote == [], f"UI loads remote assets: {remote}"

    def test_no_build_step_artifacts(self) -> None:
        from pathlib import Path

        import outpost.web.app as web

        templates = Path(web.__file__).parent / "templates"
        assert templates.is_dir()
        assert not (Path(web.__file__).parent / "package.json").exists()


class TestTracePanel:
    """F-08 — 30% of the score."""

    def test_trace_rows_render_in_order(
        self, client: TestClient, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        for tool in ("query_graph", "get_case_def", "raise_alert"):
            trace.record("agent", tool, {"x": 1}, connection=db)

        html = client.get("/").text
        positions = [html.index(tool) for tool in ("raise_alert", "get_case_def", "query_graph")]
        assert positions == sorted(positions), "newest first"

    def test_api_trace_returns_json(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        trace.record("worker:vision", "score_film", {"case_id": "c1"}, connection=db)
        payload = client.get("/api/trace").json()
        assert payload["trace"][0]["tool"] == "score_film"
        assert payload["trace"][0]["actor"] == "worker:vision"

    def test_errors_are_visible_not_hidden(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        trace.record(
            "worker:asr", "transcribe", {},
            result_summary="ERROR ASRUnavailable: weights missing", connection=db,
        )
        html = client.get("/").text
        assert "ERROR ASRUnavailable" in html
        assert "trace-err" in html

    def test_trace_limit_is_honoured(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        for index in range(60):
            trace.record("agent", f"tool-{index}", {}, connection=db)
        assert len(client.get("/api/trace?limit=10").json()["trace"]) == 10


class TestAlertReview:
    """F-09 — approve / dismiss."""

    def test_alert_renders_with_rationale_and_cases(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        seed_alert(db)
        html = client.get("/").text
        assert "acute watery diarrhoea" in html
        assert "sector-4" in html
        assert "review recommended" in html
        for case_id in ("case-0421", "case-0422", "case-0423"):
            assert case_id in html

    def test_both_buttons_are_present(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        alert_id = seed_alert(db)
        html = client.get("/").text
        assert f"/alerts/{alert_id}/approve" in html
        assert f"/alerts/{alert_id}/dismiss" in html

    def test_approve_transmits_and_redirects(
        self, client: TestClient, db: sqlite3.Connection, test_settings: Settings,
        monkeypatch,
    ) -> None:
        alert_id = seed_alert(db)
        sent: list[int] = []
        monkeypatch.setattr(
            egress, "send", lambda p, **k: (sent.append(p.byte_size()), p.byte_size())[1]
        )

        response = client.post(f"/alerts/{alert_id}/approve", follow_redirects=False)
        assert response.status_code == 303
        assert len(sent) == 1

        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["status"] == "approved"
        assert row["bytes_sent"] == sent[0]

    def test_dismiss_transmits_nothing(
        self, client: TestClient, db: sqlite3.Connection, monkeypatch
    ) -> None:
        alert_id = seed_alert(db)
        monkeypatch.setattr(
            egress, "send", lambda *a, **k: pytest.fail("dismiss must not transmit")
        )

        assert client.post(
            f"/alerts/{alert_id}/dismiss", follow_redirects=False
        ).status_code == 303

        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["status"] == "dismissed"
        assert row["bytes_sent"] is None

    def test_failed_egress_leaves_alert_pending(
        self, client: TestClient, db: sqlite3.Connection, monkeypatch
    ) -> None:
        """Receiver down must not lose the alert."""
        alert_id = seed_alert(db)
        monkeypatch.setattr(
            egress, "send",
            lambda *a, **k: (_ for _ in ()).throw(egress.EgressBlocked("refused")),
        )

        response = client.post(f"/alerts/{alert_id}/approve", follow_redirects=False)
        assert response.status_code == 303

        row = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        assert row["status"] == "pending"
        assert row["bytes_sent"] is None

    def test_decided_alerts_move_to_history(
        self, client: TestClient, db: sqlite3.Connection, monkeypatch
    ) -> None:
        alert_id = seed_alert(db)
        monkeypatch.setattr(egress, "send", lambda p, **k: p.byte_size())
        client.post(f"/alerts/{alert_id}/approve", follow_redirects=False)

        html = client.get("/").text
        assert "approved" in html
        assert "Approve &amp; transmit" not in html or "No alerts" in html


class TestEgressPreview:
    """Show exactly what leaves, before anyone approves it."""

    def test_preview_shows_payload_and_byte_count(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        alert_id = seed_alert(db)
        data = client.get(f"/api/egress-preview/{alert_id}").json()

        assert data["bytes"] < 1024
        assert data["limit"] == 1024
        assert set(data["payload"]) == {
            "syndrome", "catchment", "count", "window_hours", "trend", "site_id"
        }
        assert data["payload"]["count"] == 3

    def test_preview_contains_no_identifiers(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        alert_id = seed_alert(db)
        encoded = json.dumps(client.get(f"/api/egress-preview/{alert_id}").json()["payload"])
        for case_id in ("case-0421", "case-0422", "case-0423"):
            assert case_id not in encoded

    def test_unknown_alert_returns_404(self, client: TestClient) -> None:
        assert client.get("/api/egress-preview/nope").status_code == 404


class TestCaseDetail:
    """F-11 — audio, native transcript and English side by side."""

    def test_shows_both_transcripts(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        seed_case(db)
        html = client.get("/case/case-0421").text
        assert "le patient rapporte des selles liquides" in html
        assert "the patient reports profuse watery stools" in html

    def test_shows_film_score_and_findings(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        seed_case(db)
        html = client.get("/case/case-0421").text
        assert "73" in html
        assert "patchy opacity right base" in html

    def test_never_phrases_output_as_diagnosis(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        """Invariant 4."""
        seed_case(db)
        html = client.get("/case/case-0421").text.lower()
        assert "not a diagnosis" in html
        for forbidden in ("diagnosed with", "confirmed case of", "rule out"):
            assert forbidden not in html

    def test_unknown_case_still_renders(self, client: TestClient) -> None:
        response = client.get("/case/does-not-exist")
        assert response.status_code == 200
        assert "No transcript" in response.text


class TestByteCounters:
    """F-10 — bytes_sent next to bytes_on_box."""

    def test_status_exposes_both_counters(self, client: TestClient) -> None:
        status = client.get("/api/status").json()
        assert "bytes_sent" in status
        assert "bytes_on_box" in status

    def test_dashboard_renders_both(self, client: TestClient) -> None:
        html = client.get("/").text
        assert "Bytes on box" in html
        assert "Bytes sent" in html

    def test_ratio_appears_after_transmission(
        self, client: TestClient, db: sqlite3.Connection, monkeypatch
    ) -> None:
        seed_case(db)
        alert_id = seed_alert(db)
        monkeypatch.setattr(egress, "send", lambda p, **k: p.byte_size())
        client.post(f"/alerts/{alert_id}/approve", follow_redirects=False)

        status = client.get("/api/status").json()
        assert status["bytes_sent"] > 0
        assert status["bytes_on_box"] > status["bytes_sent"]
        assert status["ratio"] > 1
        assert "Kept : sent" in client.get("/").text


class TestConcurrency:
    """PRD §7 — the heartbeat must not block the UI, and vice versa."""

    def test_ui_stays_responsive_while_heartbeat_runs(
        self, client: TestClient, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        errors: list[Exception] = []
        stop = threading.Event()

        def beat() -> None:
            while not stop.is_set():
                try:
                    heartbeat.run_cycle(use_agent=False, config=test_settings)
                except Exception as exc:  # WAL should prevent lock errors
                    errors.append(exc)
                time.sleep(0.02)

        worker = threading.Thread(target=beat, daemon=True)
        worker.start()
        try:
            latencies = []
            for _ in range(12):
                started = time.perf_counter()
                assert client.get("/").status_code == 200
                latencies.append(time.perf_counter() - started)
        finally:
            stop.set()
            worker.join(timeout=5)

        assert errors == [], f"heartbeat errored under concurrent UI load: {errors[:2]}"
        assert max(latencies) < 5.0, f"UI blocked for {max(latencies):.1f}s"
