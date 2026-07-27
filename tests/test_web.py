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
        assert "No cases yet" in html


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


class TestPipelineView:
    """The pipeline diagram is how a judge reads the system without narration."""

    def test_all_six_stages_render(self, client: TestClient) -> None:
        html = client.get("/").text
        for stage in ("st-inbox", "st-workers", "st-graph",
                      "st-heartbeat", "st-review", "st-egress"):
            assert f'id="{stage}"' in html

    def test_stage_labels_describe_the_guarantees(self, client: TestClient) -> None:
        html = client.get("/").text
        assert "structured fields only" in html
        assert "nothing moves without it" in html
        assert "counts only" in html

    def test_pipeline_api_shape(self, client: TestClient) -> None:
        data = client.get("/api/pipeline").json()
        assert set(data) == {
            "inbox", "workers", "graph", "heartbeat", "review", "egress"
        }
        assert data["heartbeat"]["interval"] == 1  # test_settings
        assert data["egress"]["bytes_sent"] == 0

    def test_pipeline_counts_reflect_work(
        self, client: TestClient, db: sqlite3.Connection
    ) -> None:
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, status, enqueued_at)"
            " VALUES ('c1', '/x.wav', 'audio', 'h1', 'done', datetime('now'))"
        )
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, status, enqueued_at)"
            " VALUES ('c2', '/y.png', 'image', 'h2', 'queued', datetime('now'))"
        )
        data = client.get("/api/pipeline").json()
        assert data["workers"]["audio"] == 1
        assert data["inbox"]["queued"] == 1
        assert data["inbox"]["total"] == 2

    def test_models_endpoint_is_local(self, client: TestClient) -> None:
        data = client.get("/api/models").json()
        assert "127.0.0.1" in data["host"] or "localhost" in data["host"]
        assert isinstance(data["models"], list)


class TestDragAndDropUpload:
    """The doctor workflow: save a file, walk away."""

    def test_dropzone_is_present(self, client: TestClient) -> None:
        html = client.get("/").text
        assert 'id="dropzone"' in html
        assert "Drop consultation files here" in html

    def test_upload_lands_in_the_watched_inbox(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        """Uploads must go through the normal ingest path, not a parallel one."""
        response = client.post(
            "/api/upload",
            files=[("files", ("case-9001.txt", b"watery stools", "text/plain"))],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["accepted"][0]["case_id"] == "case-9001"
        assert body["accepted"][0]["kind"] == "note"

        landed = test_settings.inbox_dir / "case-9001.txt"
        assert landed.is_file()
        assert landed.read_bytes() == b"watery stools"

    def test_multiple_files_group_into_one_case(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        response = client.post(
            "/api/upload",
            files=[
                ("files", ("case-9002.txt", b"note", "text/plain")),
                ("files", ("case-9002.wav", b"RIFFfake", "audio/wav")),
                ("files", ("case-9002.jpg", b"\xff\xd8fake", "image/jpeg")),
            ],
        )
        accepted = response.json()["accepted"]
        assert len({a["case_id"] for a in accepted}) == 1
        assert {a["kind"] for a in accepted} == {"note", "audio", "image"}

    @pytest.mark.parametrize(
        "filename",
        [
            "../../../etc/passwd",
            "..%2f..%2fetc%2fpasswd.txt",
            "/etc/cron.d/evil.txt",
            "..\\..\\windows\\system32\\evil.txt",
        ],
    )
    def test_path_traversal_cannot_escape_the_inbox(
        self, client: TestClient, test_settings: Settings, filename: str
    ) -> None:
        """Browser-supplied filenames are untrusted input written to disk."""
        client.post("/api/upload", files=[("files", (filename, b"x", "text/plain"))])

        # Anything written must sit directly in the inbox. Ignore SQLite's own
        # sidecar files, which legitimately live one level up in the data root.
        written = [
            path
            for path in test_settings.data_root.rglob("*")
            if path.is_file() and not path.name.startswith("outpost.db")
        ]
        for path in written:
            assert path.parent == test_settings.inbox_dir, (
                f"{filename!r} escaped to {path}"
            )
            # The directory components must be gone, not merely neutralised.
            assert ".." not in path.name
            assert "/" not in path.name and "\\" not in path.name

    @pytest.mark.parametrize(
        "filename", ["scan.dcm", "notes.pdf", "clip.mp4", "payload.sh", "noext"]
    )
    def test_unsupported_types_are_rejected(
        self, client: TestClient, test_settings: Settings, filename: str
    ) -> None:
        response = client.post(
            "/api/upload", files=[("files", (filename, b"x", "application/octet-stream"))]
        )
        assert response.status_code == 422
        assert response.json()["rejected"]
        assert not (test_settings.inbox_dir / filename).exists()

    def test_empty_file_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/upload", files=[("files", ("case-1.txt", b"", "text/plain"))]
        )
        assert response.status_code == 422

    def test_uploaded_file_is_deduped_by_the_watcher(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        """Uploads share the watcher's dedupe because they share its folder."""
        from outpost import watcher

        for _ in range(2):
            client.post(
                "/api/upload",
                files=[("files", ("case-9003.txt", b"identical", "text/plain"))],
            )
        results = watcher.scan_existing(test_settings)
        queued = [r for r in results if not r.duplicate]
        assert len(queued) == 1


    def test_upload_records_catchment_for_the_graph(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        """A browser-uploaded case must join the right catchment.

        Without this it falls back to the site default and never joins the
        cluster it belongs to — which silently breaks the drag-and-drop demo.
        """
        response = client.post(
            "/api/upload",
            files=[("files", ("case-9100.txt", b"watery stools", "text/plain"))],
            data={"catchment": "sector-4"},
        )
        assert response.json()["catchment"] == "sector-4"

        manifest = test_settings.catchment_manifest
        assert manifest.is_file()
        assert "case-9100\tsector-4" in manifest.read_text()

    def test_catchment_is_sanitised(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        client.post(
            "/api/upload",
            files=[("files", ("case-9101.txt", b"x", "text/plain"))],
            data={"catchment": "../../evil sector!"},
        )
        content = test_settings.catchment_manifest.read_text()
        assert ".." not in content
        assert "/" not in content.replace("\n", "")

    def test_manifest_accumulates_across_uploads(
        self, client: TestClient, test_settings: Settings
    ) -> None:
        """A second upload must not wipe the first case's catchment."""
        for index, sector in ((1, "sector-4"), (2, "sector-9")):
            client.post(
                "/api/upload",
                files=[("files", (f"case-920{index}.txt", b"x", "text/plain"))],
                data={"catchment": sector},
            )
        content = test_settings.catchment_manifest.read_text()
        assert "case-9201\tsector-4" in content
        assert "case-9202\tsector-9" in content

    def test_uploaded_case_reaches_the_right_catchment(
        self, client: TestClient, test_settings: Settings, db: sqlite3.Connection
    ) -> None:
        """End to end: upload -> watcher -> heartbeat -> correct catchment."""
        from outpost import watcher
        from outpost.agent import heartbeat

        client.post(
            "/api/upload",
            files=[("files", ("case-9300.txt", b"profuse watery stools", "text/plain"))],
            data={"catchment": "sector-7"},
        )
        watcher.scan_existing(test_settings, connection=db)
        heartbeat.process_jobs(connection=db, config=test_settings)

        row = db.execute(
            "SELECT catchment FROM cases WHERE case_id = 'case-9300'"
        ).fetchone()
        assert row is not None, "uploaded case never reached the graph"
        assert row["catchment"] == "sector-7"


class TestSafeFilename:
    """Unit-level guard on the sanitiser itself."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("case-0421.txt", "case-0421.txt"),
            ("Case_0421.WAV", "Case_0421.wav"),
            ("/tmp/case-1.png", "case-1.png"),
            ("../../case-1.txt", "case-1.txt"),
            ("C:\\temp\\case-1.jpg", "case-1.jpg"),
            ("weird name!@#.txt", "weird_name.txt"),
        ],
    )
    def test_sanitises(self, raw: str, expected: str) -> None:
        from outpost.web.app import safe_filename

        assert safe_filename(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["", "..", ".", "evil.sh", "noextension", "../..", ".hidden"]
    )
    def test_rejects(self, raw: str) -> None:
        from outpost.web.app import safe_filename

        assert safe_filename(raw) is None

    def test_never_returns_a_path(self) -> None:
        from outpost.web.app import safe_filename

        for raw in ("../../etc/passwd.txt", "a/b/c.txt", "..\\..\\x.txt"):
            result = safe_filename(raw)
            if result is not None:
                assert "/" not in result and "\\" not in result
                assert not result.startswith(".")


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
