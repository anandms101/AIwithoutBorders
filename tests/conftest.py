"""Shared test fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from outpost.config import Settings
from outpost.db import connect, init_db


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    """Settings pointed at an isolated temp data root."""
    root = tmp_path / "data"
    return Settings(
        data_root=root,
        db_path=root / "outpost.db",
        inbox_dir=root / "inbox",
        artifacts_dir=root / "artifacts",
        site_id="OP-TEST",
        heartbeat_seconds=1,
        alert_min_cases=3,
        alert_window_hours=72,
        egress_url="http://127.0.0.1:9000/report",
        ollama_host="http://127.0.0.1:11434",
        ollama_keep_alive=-1,
        ollama_max_loaded_models=4,
        agent_model="gemma4:12b",
        vision_model="medgemma:latest",
        embed_model="embeddinggemma:300m",
        asr_model="large-v3",
        agent_num_ctx=8192,
        vision_num_ctx=4096,
        request_timeout_seconds=180,
        asr_language="fr",
    )


@pytest.fixture
def db(test_settings: Settings) -> Iterator[sqlite3.Connection]:
    """An initialised database connection on a temp path."""
    init_db(test_settings)
    connection = connect(test_settings)
    try:
        yield connection
    finally:
        connection.close()
