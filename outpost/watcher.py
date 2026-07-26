"""F-01 — watch ``/data/inbox`` and enqueue jobs.

Contract (``docs/ARCHITECTURE.md`` §2):

* Files group into a **case** by filename stem: ``case-0421.wav``,
  ``case-0421.png`` and ``case-0421.txt`` are all case ``case-0421``.
* Dedupe on **SHA-256 content hash** — the same file dropped twice must not
  create a second case.
* Enqueue within 2 seconds of the drop.

The stability wait matters more than it looks: inotify fires on *create*, so a
large file copied into the inbox is visible long before it is complete. Hashing
it immediately would record the hash of a partial file and permanently poison
the dedupe table.
"""

from __future__ import annotations

import hashlib
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect, init_db, utcnow

CHUNK_SIZE = 1024 * 1024
STABILITY_CHECKS = 3
STABILITY_INTERVAL = 0.15


@dataclass(frozen=True)
class EnqueueResult:
    """Outcome of offering one file to the queue."""

    path: Path
    case_id: str
    kind: str
    content_hash: str
    job_id: int | None
    duplicate: bool


def case_id_for(path: Path | str) -> str:
    """Filename stem is the case id (ARCHITECTURE §2)."""
    return Path(path).stem


def content_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def wait_until_stable(path: Path, timeout: float = 10.0) -> bool:
    """Block until the file stops growing.

    inotify fires on create, not on close, so a file still being copied would
    otherwise be hashed half-written — poisoning the dedupe table with a hash
    that never recurs.
    """
    deadline = time.monotonic() + timeout
    last_size = -1
    stable_count = 0

    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False

        if size == last_size and size > 0:
            stable_count += 1
            if stable_count >= STABILITY_CHECKS:
                return True
        else:
            stable_count = 0
            last_size = size
        time.sleep(STABILITY_INTERVAL)

    return path.exists() and path.stat().st_size > 0


def enqueue_file(
    path: Path,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
    wait_stable: bool = True,
) -> EnqueueResult | None:
    """Enqueue one file. Returns None when the file is not a supported kind."""
    config = config or settings
    path = Path(path)

    kind = config.kind_for(path)
    if kind is None:
        return None

    if wait_stable and not wait_until_stable(path):
        return None

    digest = content_hash(path)
    case = case_id_for(path)

    owned = connection is None
    conn = connection or connect(config)
    try:
        try:
            cursor = conn.execute(
                "INSERT INTO jobs (case_id, path, kind, content_hash, status,"
                " enqueued_at) VALUES (?, ?, ?, ?, 'queued', ?)",
                (case, str(path), kind, digest, utcnow()),
            )
            job_id = int(cursor.lastrowid or 0)
            duplicate = False
        except sqlite3.IntegrityError:
            # content_hash UNIQUE — the same bytes are already queued.
            job_id = None
            duplicate = True

        trace.record(
            "watcher",
            "enqueue_file",
            {"path": str(path), "case_id": case, "kind": kind},
            result_summary=(
                f"duplicate hash={digest[:12]}"
                if duplicate
                else f"queued job={job_id} hash={digest[:12]}"
            ),
            connection=conn,
        )
    finally:
        if owned:
            conn.close()

    return EnqueueResult(
        path=path,
        case_id=case,
        kind=kind,
        content_hash=digest,
        job_id=job_id,
        duplicate=duplicate,
    )


def scan_existing(
    config: Settings | None = None,
    *,
    connection: sqlite3.Connection | None = None,
) -> list[EnqueueResult]:
    """Enqueue anything already sitting in the inbox.

    Run at startup so files dropped while the watcher was down are not lost,
    and so ``reset_demo.sh`` can seed the inbox before starting anything.
    """
    config = config or settings
    config.ensure_dirs()

    results: list[EnqueueResult] = []
    for path in sorted(config.inbox_dir.iterdir()):
        if not path.is_file():
            continue
        result = enqueue_file(
            path, connection=connection, config=config, wait_stable=False
        )
        if result is not None:
            results.append(result)
    return results


class InboxHandler(FileSystemEventHandler):
    """Translate filesystem events into queue entries."""

    def __init__(self, config: Settings | None = None) -> None:
        self._settings = config or settings

    def _handle(self, raw_path: str | bytes) -> None:
        path = Path(raw_path.decode() if isinstance(raw_path, bytes) else raw_path)
        try:
            enqueue_file(path, config=self._settings)
        except Exception as exc:  # never let one bad file kill the watcher
            trace.record(
                "watcher",
                "enqueue_file",
                {"path": str(path)},
                result_summary=f"ERROR {type(exc).__name__}: {exc}",
                config=self._settings,
            )

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event: FileSystemEvent) -> None:
        # `mv` into the inbox surfaces as a move, not a create.
        if not event.is_directory:
            self._handle(event.dest_path)


def run(config: Settings | None = None) -> None:
    """Watch the inbox until interrupted."""
    config = config or settings
    init_db(config)

    existing = scan_existing(config)
    queued = sum(1 for item in existing if not item.duplicate)
    print(f"[watcher] inbox   : {config.inbox_dir}")
    print(f"[watcher] backlog : {queued} queued, {len(existing) - queued} duplicate")

    observer = Observer()
    observer.schedule(InboxHandler(config), str(config.inbox_dir), recursive=False)
    observer.start()
    print("[watcher] watching — Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[watcher] stopping")
    finally:
        observer.stop()
        observer.join()


def pending_jobs(
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
    limit: int = 50,
) -> Iterable[sqlite3.Row]:
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        return conn.execute(
            "SELECT * FROM jobs WHERE status = 'queued' ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        if owned:
            conn.close()


if __name__ == "__main__":
    run()
