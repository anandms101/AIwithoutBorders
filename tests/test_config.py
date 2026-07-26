"""Step 1 gates: config resolution and the shared Ollama client contract."""

from __future__ import annotations

import json

import pytest

from outpost.config import Settings, load_settings
from outpost.llm import extract_json


def test_settings_have_architecture_defaults() -> None:
    """Defaults must match docs/ARCHITECTURE.md §8."""
    settings = load_settings()
    assert settings.site_id == "OP-001"
    assert settings.heartbeat_seconds == 30
    assert settings.alert_min_cases == 3
    assert settings.alert_window_hours == 72
    assert settings.ollama_host == "http://127.0.0.1:11434"
    assert settings.ollama_max_loaded_models >= 4


def test_keep_alive_is_integer_negative_one() -> None:
    """Invariant 6: models stay resident.

    Ollama rejects the *string* "-1" with `missing unit in duration`, so this
    must be a real int or every model call 400s.
    """
    settings = load_settings()
    assert settings.ollama_keep_alive == -1
    assert isinstance(settings.ollama_keep_alive, int)


def test_context_lengths_are_pinned() -> None:
    """Resident memory is driven by context length, not parameter count."""
    settings = load_settings()
    assert 0 < settings.agent_num_ctx <= 32768
    assert 0 < settings.vision_num_ctx <= 32768


def test_inference_endpoint_is_local_only() -> None:
    """Invariant 1: no remote inference, ever."""
    settings = load_settings()
    assert any(
        host in settings.ollama_host for host in ("127.0.0.1", "localhost", "0.0.0.0")
    )


def test_env_overrides_are_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTPOST_SITE_ID", "OP-999")
    monkeypatch.setenv("OUTPOST_ALERT_MIN_CASES", "5")
    monkeypatch.setenv("OLLAMA_KEEP_ALIVE", "10m")
    settings = load_settings()
    assert settings.site_id == "OP-999"
    assert settings.alert_min_cases == 5
    # Duration strings pass through untouched; only numerics are coerced.
    assert settings.ollama_keep_alive == "10m"


def test_bad_integer_env_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OUTPOST_ALERT_MIN_CASES", "three")
    with pytest.raises(ValueError):
        load_settings()


def test_kind_for_maps_extensions() -> None:
    settings = load_settings()
    assert settings.kind_for("case-0421.wav") == "audio"
    assert settings.kind_for("case-0421.PNG") == "image"
    assert settings.kind_for("case-0421.txt") == "note"
    assert settings.kind_for("case-0421.dcm") is None, "DICOM is a non-goal (D3)"


def test_ensure_dirs_is_idempotent(tmp_path) -> None:
    settings = Settings(
        data_root=tmp_path / "d",
        db_path=tmp_path / "d" / "outpost.db",
        inbox_dir=tmp_path / "d" / "inbox",
        artifacts_dir=tmp_path / "d" / "artifacts",
        site_id="OP-001",
        heartbeat_seconds=30,
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
    settings.ensure_dirs()
    settings.ensure_dirs()
    assert settings.inbox_dir.is_dir()
    assert settings.artifacts_dir.is_dir()


class TestExtractJson:
    """Local models wrap JSON in prose; medgemma cannot tool-call at all."""

    def test_bare_object(self) -> None:
        assert extract_json('{"score": 72}') == {"score": 72}

    def test_fenced_block(self) -> None:
        raw = 'Here you go:\n```json\n{"score": 72}\n```\nHope that helps.'
        assert extract_json(raw) == {"score": 72}

    def test_trailing_prose(self) -> None:
        assert extract_json('{"score": 72} — review recommended.') == {"score": 72}

    def test_brace_inside_string_does_not_truncate(self) -> None:
        assert extract_json('lead {"note": "has } brace"} tail') == {
            "note": "has } brace"
        }

    def test_escaped_quote_inside_string(self) -> None:
        raw = r'{"note": "he said \"hi\""}'
        assert extract_json(raw) == json.loads(raw)

    @pytest.mark.parametrize("raw", ["", "no json at all", "[1, 2, 3]", "null"])
    def test_unparseable_returns_none(self, raw: str) -> None:
        """Callers must fall back deterministically (ARCHITECTURE §5)."""
        assert extract_json(raw) is None
