"""F-03 — score a chest film for abnormality.

Contract (``docs/ARCHITECTURE.md`` §5):

* Output schema is ``{"score": int 0-100, "findings": str}``.
* Unparseable output falls back to score ``50`` /
  ``"unscored — manual review required"``. It never raises and never lets prose
  reach the database.

Two invariants shape the prompt:

* **Invariant 4** — this triages and prioritises, it never diagnoses. The score
  is a review-ordering signal, not a finding of disease.
* **Invariant 5** — ``film_findings`` is free text and must never reach alert
  logic. It is stored for the clinician to read and for nothing else.

``medgemma`` is multimodal despite Ollama reporting ``completion``-only
capability; verified directly against the API.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect, utcnow
from outpost.llm import OllamaClient, OllamaError

FALLBACK_SCORE = 50
FALLBACK_FINDINGS = "unscored — manual review required"
MAX_FINDINGS_CHARS = 400

SYSTEM_PROMPT = (
    "You are a triage assistant for a field hospital. You prioritise chest films "
    "for clinician review. You do not diagnose, confirm, or rule out disease. "
    "Reply with JSON only."
)

USER_PROMPT = """Assess this chest radiograph for triage priority.

Return ONLY a JSON object, no prose and no code fence:
{"score": <integer 0-100>, "findings": "<short phrase, max 20 words>"}

"score" is review urgency, not a diagnosis:
  0-24   appears unremarkable
  25-49  minor findings, routine review
  50-74  notable findings, prioritise review
  75-100 marked findings, review first

"findings" is a brief descriptive phrase for the clinician. Describe what is
visible. Do not name a disease and do not state a diagnosis."""


@dataclass(frozen=True)
class FilmScore:
    """Result of scoring one film."""

    case_id: str
    score: int
    findings: str
    fallback: bool

    def as_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "score": self.score, "findings": self.findings}


def _coerce(payload: dict[str, Any] | None) -> tuple[int, str] | None:
    """Validate the model payload, or return None to trigger the fallback."""
    if not payload:
        return None

    raw_score = payload.get("score")
    if isinstance(raw_score, bool):  # bool is an int subclass; reject it
        return None
    if isinstance(raw_score, str):
        try:
            raw_score = float(raw_score.strip())
        except ValueError:
            return None
    if not isinstance(raw_score, int | float):
        return None

    score = int(round(raw_score))
    if not 0 <= score <= 100:
        return None

    findings = payload.get("findings")
    if not isinstance(findings, str) or not findings.strip():
        return None

    return score, findings.strip()[:MAX_FINDINGS_CHARS]


def score_film(
    case_id: str,
    image_path: Path | str,
    *,
    client: OllamaClient | None = None,
    config: Settings | None = None,
) -> FilmScore:
    """Score one film. Always returns a usable result."""
    config = config or settings
    client = client or OllamaClient(config)
    path = Path(image_path)

    if not path.is_file():
        return FilmScore(case_id, FALLBACK_SCORE, FALLBACK_FINDINGS, fallback=True)

    try:
        payload = client.generate_json(
            config.vision_model,
            USER_PROMPT,
            system=SYSTEM_PROMPT,
            images=[path],
            num_ctx=config.vision_num_ctx,
        )
    except OllamaError:
        # Invariant: the demo path must degrade, not crash. The trace decorator
        # on the caller records why.
        return FilmScore(case_id, FALLBACK_SCORE, FALLBACK_FINDINGS, fallback=True)

    coerced = _coerce(payload)
    if coerced is None:
        return FilmScore(case_id, FALLBACK_SCORE, FALLBACK_FINDINGS, fallback=True)

    score, findings = coerced
    return FilmScore(case_id, score, findings, fallback=False)


def process(
    case_id: str,
    image_path: Path | str,
    *,
    client: OllamaClient | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> FilmScore:
    """Score a film and persist it to ``artifacts``."""
    config = config or settings

    owned = connection is None
    conn = connection or connect(config)
    try:
        trace_id = trace.record(
            "worker:vision",
            "score_film",
            {"case_id": case_id, "image_path": str(image_path)},
            connection=conn,
        )

        import time

        started = time.perf_counter()
        result = score_film(case_id, image_path, client=client, config=config)
        duration_ms = int((time.perf_counter() - started) * 1000)

        conn.execute(
            "INSERT INTO artifacts (case_id, image_path, film_score, film_findings,"
            " created_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(case_id) DO UPDATE SET"
            " image_path = excluded.image_path,"
            " film_score = excluded.film_score,"
            " film_findings = excluded.film_findings",
            (
                case_id,
                str(image_path),
                result.score,
                result.findings,
                utcnow(),
            ),
        )

        trace.update(
            trace_id,
            result_summary=(
                f"score={result.score} fallback={result.fallback} "
                f"findings={result.findings[:60]}"
            ),
            duration_ms=duration_ms,
            connection=conn,
        )
        return result
    finally:
        if owned:
            conn.close()
