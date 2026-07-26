"""Step 4 gate (F-01): enqueue within 2s, dedupe on hash, group by stem."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from watchdog.observers import Observer

from outpost import trace, watcher
from outpost.config import Settings


def _write(path: Path, content: bytes = b"payload") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _jobs(db: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY id").fetchall()]


def test_case_id_is_filename_stem() -> None:
    assert watcher.case_id_for("/data/inbox/case-0421.wav") == "case-0421"
    assert watcher.case_id_for(Path("case-0421.png")) == "case-0421"


def test_files_group_into_one_case(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """case-0421.wav + .png + .txt are one case (ARCHITECTURE §2)."""
    inbox = test_settings.inbox_dir
    for name, payload in (
        ("case-0421.wav", b"audio"),
        ("case-0421.png", b"image"),
        ("case-0421.txt", b"note"),
    ):
        watcher.enqueue_file(
            _write(inbox / name, payload),
            connection=db,
            config=test_settings,
            wait_stable=False,
        )

    jobs = _jobs(db)
    assert len(jobs) == 3
    assert {job["case_id"] for job in jobs} == {"case-0421"}
    assert {job["kind"] for job in jobs} == {"audio", "image", "note"}


def test_same_file_twice_creates_one_job(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """F-01 dedupe on SHA-256 content hash."""
    path = _write(test_settings.inbox_dir / "case-1.png", b"identical-bytes")

    first = watcher.enqueue_file(
        path, connection=db, config=test_settings, wait_stable=False
    )
    second = watcher.enqueue_file(
        path, connection=db, config=test_settings, wait_stable=False
    )

    assert first is not None and not first.duplicate
    assert second is not None and second.duplicate
    assert second.job_id is None
    assert len(_jobs(db)) == 1


def test_same_bytes_different_name_is_still_a_duplicate(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """Dedupe is on content, not filename."""
    inbox = test_settings.inbox_dir
    watcher.enqueue_file(
        _write(inbox / "case-1.png", b"same"),
        connection=db,
        config=test_settings,
        wait_stable=False,
    )
    result = watcher.enqueue_file(
        _write(inbox / "case-2.png", b"same"),
        connection=db,
        config=test_settings,
        wait_stable=False,
    )

    assert result is not None and result.duplicate
    assert len(_jobs(db)) == 1


def test_different_bytes_are_separate_jobs(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    inbox = test_settings.inbox_dir
    watcher.enqueue_file(
        _write(inbox / "case-1.png", b"aaa"),
        connection=db,
        config=test_settings,
        wait_stable=False,
    )
    watcher.enqueue_file(
        _write(inbox / "case-2.png", b"bbb"),
        connection=db,
        config=test_settings,
        wait_stable=False,
    )
    assert len(_jobs(db)) == 2


@pytest.mark.parametrize("name", ["scan.dcm", "notes.pdf", "clip.mp4", "no_extension"])
def test_unsupported_kinds_are_ignored(
    db: sqlite3.Connection, test_settings: Settings, name: str
) -> None:
    """D3: DICOM is a non-goal; video is not an input."""
    result = watcher.enqueue_file(
        _write(test_settings.inbox_dir / name),
        connection=db,
        config=test_settings,
        wait_stable=False,
    )
    assert result is None
    assert _jobs(db) == []


def test_enqueue_is_traced(db: sqlite3.Connection, test_settings: Settings) -> None:
    watcher.enqueue_file(
        _write(test_settings.inbox_dir / "case-9.png"),
        connection=db,
        config=test_settings,
        wait_stable=False,
    )
    rows = trace.recent(connection=db)
    assert any(r["tool"] == "enqueue_file" and r["actor"] == "watcher" for r in rows)


def test_scan_existing_picks_up_backlog(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """Files dropped while the watcher was down must not be lost."""
    inbox = test_settings.inbox_dir
    _write(inbox / "case-a.png", b"a")
    _write(inbox / "case-b.wav", b"b")
    _write(inbox / "ignore.dcm", b"c")

    results = watcher.scan_existing(test_settings, connection=db)

    assert len(results) == 2
    assert {r.case_id for r in results} == {"case-a", "case-b"}


def test_scan_existing_is_idempotent(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    _write(test_settings.inbox_dir / "case-a.png", b"a")
    watcher.scan_existing(test_settings, connection=db)
    watcher.scan_existing(test_settings, connection=db)
    assert len(_jobs(db)) == 1


def test_wait_until_stable_rejects_missing_file(tmp_path: Path) -> None:
    assert watcher.wait_until_stable(tmp_path / "nope.png", timeout=0.5) is False


def test_content_hash_matches_known_sha256(tmp_path: Path) -> None:
    import hashlib

    path = _write(tmp_path / "x.png", b"outpost")
    assert watcher.content_hash(path) == hashlib.sha256(b"outpost").hexdigest()


def test_live_watcher_enqueues_within_two_seconds(test_settings: Settings) -> None:
    """F-01 latency requirement, exercised through a real inotify observer."""
    from outpost.db import connect, init_db

    init_db(test_settings)
    test_settings.ensure_dirs()

    observer = Observer()
    observer.schedule(
        watcher.InboxHandler(test_settings), str(test_settings.inbox_dir), recursive=False
    )
    observer.start()
    try:
        time.sleep(0.3)  # let inotify arm
        started = time.monotonic()
        _write(test_settings.inbox_dir / "case-live.png", b"live-bytes")

        deadline = started + 2.0
        found = False
        while time.monotonic() < deadline:
            with connect(test_settings) as conn:
                rows = conn.execute(
                    "SELECT case_id FROM jobs WHERE case_id = 'case-live'"
                ).fetchall()
            if rows:
                found = True
                break
            time.sleep(0.05)

        elapsed = time.monotonic() - started
        assert found, f"not enqueued within 2s (waited {elapsed:.2f}s)"
        assert elapsed < 2.0
    finally:
        observer.stop()
        observer.join()
