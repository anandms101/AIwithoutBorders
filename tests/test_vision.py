"""Step 5 gate (F-03): strict JSON, validated range, deterministic fallback."""

from __future__ import annotations

import sqlite3
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest

from outpost.config import Settings
from outpost.llm import OllamaError
from outpost.workers import vision


def make_png(path: Path, width: int = 64, height: int = 64) -> Path:
    """A real, decodable greyscale PNG — no test-only image library needed."""
    raw = b""
    for y in range(height):
        raw += b"\x00" + bytes([(x * 4 + y * 2) % 256 for x in range(width)])

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return path


class FakeClient:
    """Stands in for OllamaClient so fallbacks are testable without a model."""

    def __init__(self, payload: Any = None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error
        self.calls = 0

    def generate_json(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def test_valid_payload_is_used(tmp_path: Path, test_settings: Settings) -> None:
    client = FakeClient({"score": 82, "findings": "dense opacity, right upper zone"})
    result = vision.score_film(
        "case-1", make_png(tmp_path / "f.png"), client=client, config=test_settings
    )
    assert result.score == 82
    assert result.findings == "dense opacity, right upper zone"
    assert result.fallback is False


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"score": 82},
        {"findings": "only text"},
        {"score": 101, "findings": "out of range"},
        {"score": -1, "findings": "negative"},
        {"score": "high", "findings": "not a number"},
        {"score": True, "findings": "bool is not a score"},
        {"score": 50, "findings": ""},
        {"score": 50, "findings": "   "},
        {"score": 50, "findings": 12345},
        {"score": None, "findings": "null score"},
    ],
)
def test_unparseable_output_falls_back(
    tmp_path: Path, test_settings: Settings, payload: Any
) -> None:
    """ARCHITECTURE §5: never let unparseable prose reach the database."""
    client = FakeClient(payload)
    result = vision.score_film(
        "case-1", make_png(tmp_path / "f.png"), client=client, config=test_settings
    )
    assert result.score == vision.FALLBACK_SCORE == 50
    assert result.findings == vision.FALLBACK_FINDINGS
    assert result.fallback is True


def test_model_error_falls_back_without_raising(
    tmp_path: Path, test_settings: Settings
) -> None:
    """The demo path degrades; it does not crash."""
    client = FakeClient(error=OllamaError("connection refused"))
    result = vision.score_film(
        "case-1", make_png(tmp_path / "f.png"), client=client, config=test_settings
    )
    assert result.fallback is True
    assert result.score == 50


def test_missing_image_falls_back(tmp_path: Path, test_settings: Settings) -> None:
    client = FakeClient({"score": 90, "findings": "should not be used"})
    result = vision.score_film(
        "case-1", tmp_path / "absent.png", client=client, config=test_settings
    )
    assert result.fallback is True
    assert client.calls == 0, "must not call the model for a missing file"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(0, 0), (100, 100), (49.6, 50), ("73", 73), (73.0, 73)],
)
def test_score_boundaries_and_coercion(
    tmp_path: Path, test_settings: Settings, raw: Any, expected: int
) -> None:
    client = FakeClient({"score": raw, "findings": "edge"})
    result = vision.score_film(
        "case-1", make_png(tmp_path / "f.png"), client=client, config=test_settings
    )
    assert result.score == expected
    assert result.fallback is False


def test_long_findings_are_truncated(tmp_path: Path, test_settings: Settings) -> None:
    client = FakeClient({"score": 60, "findings": "x" * 5000})
    result = vision.score_film(
        "case-1", make_png(tmp_path / "f.png"), client=client, config=test_settings
    )
    assert len(result.findings) <= vision.MAX_FINDINGS_CHARS


def test_process_persists_and_traces(
    db: sqlite3.Connection, tmp_path: Path, test_settings: Settings
) -> None:
    client = FakeClient({"score": 77, "findings": "patchy consolidation"})
    image = make_png(tmp_path / "case-0421.png")

    vision.process(
        "case-0421", image, client=client, connection=db, config=test_settings
    )

    row = db.execute(
        "SELECT film_score, film_findings FROM artifacts WHERE case_id = ?",
        ("case-0421",),
    ).fetchone()
    assert row["film_score"] == 77
    assert row["film_findings"] == "patchy consolidation"

    traced = db.execute(
        "SELECT tool, result_summary FROM trace WHERE actor = 'worker:vision'"
    ).fetchall()
    assert len(traced) == 1
    assert traced[0]["tool"] == "score_film"
    assert "score=77" in traced[0]["result_summary"]


def test_process_is_idempotent(
    db: sqlite3.Connection, tmp_path: Path, test_settings: Settings
) -> None:
    image = make_png(tmp_path / "case-0421.png")
    vision.process(
        "case-0421",
        image,
        client=FakeClient({"score": 10, "findings": "first"}),
        connection=db,
        config=test_settings,
    )
    vision.process(
        "case-0421",
        image,
        client=FakeClient({"score": 90, "findings": "second"}),
        connection=db,
        config=test_settings,
    )

    rows = db.execute("SELECT film_score FROM artifacts WHERE case_id = ?",
                      ("case-0421",)).fetchall()
    assert len(rows) == 1, "one artifacts row per case"
    assert rows[0]["film_score"] == 90


def test_prompt_forbids_diagnosis() -> None:
    """Invariant 4: it triages and prioritises, it never diagnoses."""
    combined = (vision.SYSTEM_PROMPT + vision.USER_PROMPT).lower()
    assert "do not diagnose" in combined
    assert "not a diagnosis" in combined
    assert "triage" in combined


@pytest.mark.live
def test_live_medgemma_returns_valid_score(
    tmp_path: Path, test_settings: Settings
) -> None:
    """Real model call. medgemma is multimodal despite Ollama's metadata."""
    from outpost.llm import OllamaClient

    client = OllamaClient(test_settings)
    if not client.health():
        pytest.skip("Ollama not reachable")

    result = vision.score_film(
        "case-live", make_png(tmp_path / "film.png"), config=test_settings
    )
    assert 0 <= result.score <= 100
    assert result.findings
    assert not result.fallback, "live model should produce parseable JSON"
