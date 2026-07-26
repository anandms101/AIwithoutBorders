"""Step 2 gate: schema matches ARCHITECTURE §3, WAL on, migrations idempotent."""

from __future__ import annotations

import sqlite3

import pytest

from outpost.config import Settings
from outpost.db import TABLES, connect, init_db, table_names, transaction, utcnow


def test_all_eight_tables_created(db: sqlite3.Connection) -> None:
    assert set(TABLES).issubset(table_names(db))
    assert len(TABLES) == 8


def test_cases_window_index_exists(db: sqlite3.Connection) -> None:
    """Alert queries filter on (syndrome_code, catchment, occurred_at)."""
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index'"
    ).fetchall()
    assert "idx_cases_window" in {row["name"] for row in rows}


def test_journal_mode_is_wal(db: sqlite3.Connection) -> None:
    """Invariant 7: durable on disk, and readable while workers write."""
    assert db.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_init_db_is_idempotent(test_settings: Settings) -> None:
    init_db(test_settings)
    init_db(test_settings)
    init_db(test_settings)
    with connect(test_settings) as conn:
        assert set(TABLES).issubset(table_names(conn))


def test_jobs_content_hash_is_unique(db: sqlite3.Connection) -> None:
    """F-01 dedupe: the same file dropped twice must not create two jobs."""
    for _ in range(1):
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("case-0421", "/data/inbox/case-0421.png", "image", "abc123", utcnow()),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("case-0422", "/data/inbox/copy.png", "image", "abc123", utcnow()),
        )


@pytest.mark.parametrize("bad_kind", ["video", "dicom", ""])
def test_jobs_kind_is_constrained(db: sqlite3.Connection, bad_kind: str) -> None:
    """D3: PNG/JPEG only, no DICOM."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("case-1", "/x", bad_kind, f"hash-{bad_kind}", utcnow()),
        )


def test_alert_status_is_constrained(db: sqlite3.Connection) -> None:
    """F-09: only pending/approved/dismissed."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO alerts (id, severity, syndrome_code, catchment,"
            " case_ids_json, window_hours, rationale_text, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("a1", "high", "awd", "sector-4", "[]", 72, "because", "sent", utcnow()),
        )


def test_node_type_is_constrained(db: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO nodes (id, type, created_at) VALUES (?, ?, ?)",
            ("thing:1", "thing", utcnow()),
        )


def test_edges_require_existing_nodes(db: sqlite3.Connection) -> None:
    """Foreign keys must actually be enforced, not just declared."""
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO edges (src, dst, rel, created_at) VALUES (?, ?, ?, ?)",
            ("patient:missing", "visit:missing", "had_visit", utcnow()),
        )


def test_transaction_rolls_back_on_error(test_settings: Settings) -> None:
    init_db(test_settings)
    with pytest.raises(RuntimeError):
        with transaction(config=test_settings) as conn:
            conn.execute(
                "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
                " VALUES (?, ?, ?, ?, ?)",
                ("case-x", "/x", "image", "rollback-me", utcnow()),
            )
            raise RuntimeError("boom")

    with connect(test_settings) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE content_hash = 'rollback-me'"
        ).fetchone()[0]
    assert count == 0


def test_transaction_commits_on_success(test_settings: Settings) -> None:
    init_db(test_settings)
    with transaction(config=test_settings) as conn:
        conn.execute(
            "INSERT INTO jobs (case_id, path, kind, content_hash, enqueued_at)"
            " VALUES (?, ?, ?, ?, ?)",
            ("case-y", "/y", "note", "keep-me", utcnow()),
        )
    with connect(test_settings) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE content_hash = 'keep-me'"
        ).fetchone()[0]
    assert count == 1


def test_utcnow_is_iso_and_tz_aware() -> None:
    stamp = utcnow()
    assert stamp.endswith("+00:00")
    assert "T" in stamp
