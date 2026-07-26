"""Step 7 + 11 gates: F-02 ASR and the F-06 heartbeat loop."""

from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from outpost.agent import heartbeat
from outpost.config import Settings
from outpost.workers import asr

# Set OUTPOST_TEST_AUDIO to a real French .wav to run the live ASR gate.
# BUILD_PLAN requires real recorded audio, not synthetic.
LIVE_AUDIO = os.environ.get("OUTPOST_TEST_AUDIO", "")


class TestASRContract:
    def test_missing_file_raises_clearly(self, test_settings: Settings) -> None:
        with pytest.raises(asr.ASRUnavailable, match="not found"):
            asr.transcribe("case-1", "/nope/missing.wav", config=test_settings)

    def test_transcription_exposes_f02_schema(self) -> None:
        result = asr.Transcription("c1", "fr", "bonjour", "hello", 10)
        assert set(result.as_dict()) == {
            "source_language", "native_transcript", "english_text",
        }

    def test_never_downloads_weights_at_runtime(self) -> None:
        """AGENTS.md: no network access at build time; the venue has no Wi-Fi."""
        source = Path(asr.__file__).read_text()
        assert "local_files_only=True" in source


class TestHeartbeatCycle:
    def test_idle_cycle_is_under_ten_seconds(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """PRD §7: heartbeat cycle < 10s when there are no new cases."""
        started = time.perf_counter()
        result = heartbeat.run_cycle(
            use_agent=False, connection=db, config=test_settings
        )
        elapsed = time.perf_counter() - started

        assert elapsed < 10.0, f"idle cycle took {elapsed:.1f}s"
        assert result.idle
        assert result.jobs_processed == 0
        assert result.alerts_raised == []

    def test_cycle_is_traced_with_one_cycle_id(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        result = heartbeat.run_cycle(
            use_agent=False, connection=db, config=test_settings
        )
        rows = db.execute(
            "SELECT tool, cycle_id FROM trace WHERE actor = 'heartbeat' ORDER BY id"
        ).fetchall()

        assert [r["tool"] for r in rows] == ["cycle_start", "cycle_end"]
        assert {r["cycle_id"] for r in rows} == {result.cycle_id}

    def test_cycle_id_is_cleared_after_the_pass(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        from outpost import trace

        heartbeat.run_cycle(use_agent=False, connection=db, config=test_settings)
        assert trace.current_cycle() is None

    def test_failed_job_is_recorded_not_swallowed(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """AGENTS.md: do not silently swallow exceptions on the demo path."""
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
            " VALUES ('case-x', '/nonexistent/a.wav', 'audio', 'h1', datetime('now'))"
        )

        heartbeat.process_jobs(connection=db, config=test_settings)

        job = db.execute("SELECT * FROM jobs WHERE case_id='case-x'").fetchone()
        assert job["status"] == "failed"
        assert job["error"]
        assert job["attempts"] == 1

        traced = db.execute(
            "SELECT result_summary FROM trace WHERE tool = 'process_job'"
        ).fetchone()
        assert traced is not None and "ERROR" in traced["result_summary"]

    def test_note_job_flows_into_the_graph(
        self, db: sqlite3.Connection, test_settings: Settings, tmp_path: Path
    ) -> None:
        """F-01 -> F-04 -> F-05 without touching a model (keyword fallback)."""
        note = tmp_path / "case-0421.txt"
        note.write_text("patient with profuse watery stools and dehydration")
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
            " VALUES (?, ?, 'note', 'h2', datetime('now'))",
            ("case-0421", str(note)),
        )

        processed, written = heartbeat.process_jobs(
            connection=db, config=test_settings
        )
        assert processed == 1
        assert written == 1

        row = db.execute("SELECT * FROM cases WHERE case_id='case-0421'").fetchone()
        assert row["syndrome_code"] == "acute_watery_diarrhoea"

    def test_full_cycle_raises_alert_from_queued_notes(
        self, db: sqlite3.Connection, test_settings: Settings, tmp_path: Path
    ) -> None:
        """The demo path end to end, minus the models."""
        for index in range(3):
            note = tmp_path / f"case-{index}.txt"
            note.write_text("profuse watery stools with dehydration and vomiting")
            db.execute(
                "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
                " VALUES (?, ?, 'note', ?, datetime('now'))",
                (f"case-{index}", str(note), f"hash-{index}"),
            )

        result = heartbeat.run_cycle(
            use_agent=False, connection=db, config=test_settings
        )

        assert result.jobs_processed == 3
        assert result.cases_written == 3
        assert len(result.alerts_raised) == 1

        alert = db.execute("SELECT * FROM alerts").fetchone()
        assert alert["status"] == "pending", "invariant 3: nothing transmits here"

    def test_status_reports_counts(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        state = heartbeat.status(connection=db, config=test_settings)
        assert set(state) == {
            "jobs_queued", "jobs_done", "jobs_failed",
            "cases", "alerts_pending", "trace_rows",
        }
        assert all(isinstance(value, int) for value in state.values())


@pytest.mark.asr
@pytest.mark.skipif(not LIVE_AUDIO, reason="set OUTPOST_TEST_AUDIO to a French .wav")
def test_live_french_transcription(test_settings: Settings) -> None:
    """F-02 gate against real recorded French (D11, MediaSpeech FR baseline)."""
    result = asr.transcribe("case-live", LIVE_AUDIO, config=test_settings)

    assert result.source_language == "fr"
    assert result.native_transcript.strip(), "native transcript must not be empty"
    assert result.english_text.strip(), "English translation must not be empty"
    assert result.native_transcript != result.english_text
