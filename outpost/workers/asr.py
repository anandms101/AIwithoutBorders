"""F-02 — speech to English translation, one pass.

Whisper large-v3 via CTranslate2 (``faster-whisper``). Demo language is French
(D11): Whisper is ~5-6% WER on French versus 37.8% on Levantine and 84.7% on
Maghrebi Arabic, and at one word in three wrong a live transcript is a demo
failure.

Whisper's ``translate`` task always targets English, so native transcript and
English translation need two passes over the same decoded audio. That is still
"one pass" in the sense F-02 means — one worker invocation, no human step.

The model is loaded lazily and cached process-wide: large-v3 takes ~20s to
initialise, which must not happen inside a heartbeat cycle.

**No weights are downloaded at runtime** (AGENTS.md working conventions). If
the model is not in the local cache this fails loudly and tells you to run
``scripts/fetch_asr_model.sh`` while you still have internet.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect, utcnow

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}


class ASRUnavailable(RuntimeError):
    """faster-whisper is not installed, or the weights are not cached."""


@dataclass(frozen=True)
class Transcription:
    """Result of transcribing one audio file."""

    case_id: str
    source_language: str
    native_transcript: str
    english_text: str
    duration_ms: int

    def as_dict(self) -> dict[str, str]:
        return {
            "source_language": self.source_language,
            "native_transcript": self.native_transcript,
            "english_text": self.english_text,
        }


def is_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return False
    return True


def load_model(config: Settings | None = None) -> Any:
    """Load and cache the Whisper model.

    ``local_files_only=True`` is deliberate: a runtime download would either
    hang forever at the venue or quietly violate the offline guarantee.
    """
    config = config or settings
    name = config.asr_model

    with _model_lock:
        if name in _model_cache:
            return _model_cache[name]

        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise ASRUnavailable(
                "faster-whisper is not installed. "
                "Run: uv pip install -r requirements-asr.txt"
            ) from exc

        try:
            model = WhisperModel(
                name,
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
        except Exception as exc:
            raise ASRUnavailable(
                f"Whisper weights for {name!r} are not in the local cache. "
                "Run scripts/fetch_asr_model.sh while you still have internet."
            ) from exc

        _model_cache[name] = model
        return model


def _join(segments: Any) -> str:
    return " ".join(segment.text.strip() for segment in segments).strip()


def transcribe(
    case_id: str,
    audio_path: Path | str,
    *,
    config: Settings | None = None,
) -> Transcription:
    """Transcribe in the source language and translate to English."""
    config = config or settings
    path = Path(audio_path)

    if not path.is_file():
        raise ASRUnavailable(f"audio file not found: {path}")

    model = load_model(config)
    started = time.perf_counter()

    native_segments, info = model.transcribe(
        str(path),
        language=config.asr_language,
        task="transcribe",
        beam_size=1,
        vad_filter=True,
    )
    native_text = _join(native_segments)

    english_segments, _ = model.transcribe(
        str(path),
        language=config.asr_language,
        task="translate",  # Whisper's translate target is always English
        beam_size=1,
        vad_filter=True,
    )
    english_text = _join(english_segments)

    return Transcription(
        case_id=case_id,
        source_language=getattr(info, "language", config.asr_language),
        native_transcript=native_text,
        english_text=english_text,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def process(
    case_id: str,
    audio_path: Path | str,
    *,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
    retries: int = 1,
) -> Transcription | None:
    """Transcribe, persist, and map the English text to a syndrome.

    Returns ``None`` after exhausting retries; the failure is in the trace and
    the job is marked failed by the caller.
    """
    from outpost.workers import casedef

    config = config or settings
    owned = connection is None
    conn = connection or connect(config)
    try:
        trace_id = trace.record(
            "worker:asr",
            "transcribe",
            {"case_id": case_id, "audio_path": str(audio_path)},
            connection=conn,
            config=config,
        )
        started = time.perf_counter()

        result: Transcription | None = None
        last_error: Exception | None = None
        for _ in range(retries + 1):
            try:
                result = transcribe(case_id, audio_path, config=config)
                break
            except Exception as exc:
                last_error = exc

        duration_ms = int((time.perf_counter() - started) * 1000)

        if result is None:
            trace.update(
                trace_id,
                result_summary=f"ERROR {type(last_error).__name__}: {last_error}",
                duration_ms=duration_ms,
                connection=conn,
                config=config,
            )
            raise last_error if last_error else ASRUnavailable("transcription failed")

        conn.execute(
            "INSERT INTO artifacts (case_id, audio_path, source_language,"
            " native_transcript, english_text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO UPDATE SET"
            " audio_path = excluded.audio_path,"
            " source_language = excluded.source_language,"
            " native_transcript = excluded.native_transcript,"
            " english_text = excluded.english_text",
            (
                case_id,
                str(audio_path),
                result.source_language,
                result.native_transcript,
                result.english_text,
                utcnow(),
            ),
        )

        trace.update(
            trace_id,
            result_summary=(
                f"lang={result.source_language} "
                f"native={len(result.native_transcript)}ch "
                f"english={len(result.english_text)}ch"
            ),
            duration_ms=duration_ms,
            connection=conn,
            config=config,
        )

        # The English text is what gets mapped to a syndrome. It stays in
        # artifacts; only the resulting code reaches the surveillance view.
        if result.english_text:
            casedef.process(
                case_id, result.english_text, connection=conn, config=config
            )

        return result
    finally:
        if owned:
            conn.close()
