"""Single source of configuration (``docs/ARCHITECTURE.md`` §8).

Every value is read from the environment with a sane default. Never scatter
literals elsewhere in the package.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# ARCHITECTURE §2 specifies /data, but that path needs root on this box. The data
# root stays env-overridable so the demo box can point at /data unchanged.
_DEFAULT_DATA_ROOT = _REPO_ROOT / "data"


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


def _env_keep_alive(name: str, default: int) -> int | str:
    """Ollama wants an integer (seconds, -1 = forever) or a duration like '5m'.

    The string "-1" is rejected with `missing unit in duration`, so numeric
    values must be sent as real integers.
    """
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return raw


@dataclass(frozen=True)
class Settings:
    """Resolved runtime configuration."""

    data_root: Path
    db_path: Path
    inbox_dir: Path
    artifacts_dir: Path

    site_id: str

    heartbeat_seconds: int
    alert_min_cases: int
    alert_window_hours: int

    egress_url: str

    ollama_host: str
    ollama_keep_alive: int | str
    ollama_max_loaded_models: int

    # Model roles. Nemotron 3 Super is unavailable on this box, so the agent role
    # falls back to gemma4:12b — the only model verified end-to-end through
    # OpenClaw. See docs/DECISIONS.md.
    agent_model: str
    vision_model: str
    embed_model: str
    asr_model: str

    # Resident memory is dominated by context length, not parameter count:
    # `ollama ps` showed phi4-mini:3.8b at 20GB purely from a 131k default
    # context. Pin these or co-residency dies.
    agent_num_ctx: int
    vision_num_ctx: int

    request_timeout_seconds: int
    asr_language: str

    @property
    def catchment_manifest(self) -> Path:
        """Maps ``case_id`` -> catchment.

        The catchment must not be inferred from the consultation note. The note
        is what the model reads, and nothing the model reads may decide which
        catchment a case counts towards — that would let generated text steer
        cluster detection (invariant 5). In a real deployment this comes from
        the registration desk; here it is a TSV.
        """
        return self.data_root / "catchments.tsv"

    allowed_extensions: dict[str, str] = field(
        default_factory=lambda: {
            ".wav": "audio",
            ".m4a": "audio",
            ".mp3": "audio",
            ".png": "image",
            ".jpg": "image",
            ".jpeg": "image",
            ".txt": "note",
        }
    )

    def ensure_dirs(self) -> None:
        """Create the on-disk layout. Safe to call repeatedly."""
        for path in (self.data_root, self.inbox_dir, self.artifacts_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def kind_for(self, filename: str | Path) -> str | None:
        """Map a filename to a job kind, or None if unsupported."""
        return self.allowed_extensions.get(Path(filename).suffix.lower())


def load_settings() -> Settings:
    data_root = _env_path("OUTPOST_DATA_ROOT", _DEFAULT_DATA_ROOT)
    return Settings(
        data_root=data_root,
        db_path=_env_path("OUTPOST_DB", data_root / "outpost.db"),
        inbox_dir=_env_path("OUTPOST_INBOX", data_root / "inbox"),
        artifacts_dir=_env_path("OUTPOST_ARTIFACTS", data_root / "artifacts"),
        site_id=_env_str("OUTPOST_SITE_ID", "OP-001"),
        heartbeat_seconds=_env_int("OUTPOST_HEARTBEAT_SECONDS", 30),
        alert_min_cases=_env_int("OUTPOST_ALERT_MIN_CASES", 3),
        alert_window_hours=_env_int("OUTPOST_ALERT_WINDOW_HOURS", 72),
        egress_url=_env_str("OUTPOST_EGRESS_URL", "http://127.0.0.1:9000/report"),
        ollama_host=_env_str("OLLAMA_HOST", "http://127.0.0.1:11434"),
        ollama_keep_alive=_env_keep_alive("OLLAMA_KEEP_ALIVE", -1),
        ollama_max_loaded_models=_env_int("OLLAMA_MAX_LOADED_MODELS", 4),
        agent_model=_env_str("OUTPOST_AGENT_MODEL", "gemma4:12b"),
        vision_model=_env_str("OUTPOST_VISION_MODEL", "medgemma:latest"),
        embed_model=_env_str("OUTPOST_EMBED_MODEL", "embeddinggemma:300m"),
        asr_model=_env_str("OUTPOST_ASR_MODEL", "large-v3"),
        agent_num_ctx=_env_int("OUTPOST_AGENT_NUM_CTX", 8192),
        vision_num_ctx=_env_int("OUTPOST_VISION_NUM_CTX", 4096),
        request_timeout_seconds=_env_int("OUTPOST_REQUEST_TIMEOUT_SECONDS", 180),
        asr_language=_env_str("OUTPOST_ASR_LANGUAGE", "fr"),
    )


settings = load_settings()


if __name__ == "__main__":
    for key, value in vars(settings).items():
        print(f"{key:28} = {value}")
