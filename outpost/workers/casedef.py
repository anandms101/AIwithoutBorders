"""F-04 — map a clinical presentation to a WHO syndromic case definition.

Embedding retrieval over ``case_definitions`` using ``embeddinggemma:300m``,
with a keyword fallback so the 15:00 cut line in ``docs/BUILD_PLAN.md`` (drop
RAG, hardcode the syndrome map) is a config change rather than a rewrite.

Vectors are stored as raw float32 blobs. There are on the order of ten case
definitions, so a linear scan is exact and instant — a vector index here would
be complexity with no payoff (D2's reasoning applied to retrieval).

Per D14, definitions are paraphrased into our own schema and every row carries
the WHO adaptation disclaimer in ``source_note``. WHO material is
CC BY-NC-SA 3.0 IGO and the NC clause is a real risk given the pitch names
paying customers.
"""

from __future__ import annotations

import array
import math
import sqlite3
from dataclasses import dataclass
from typing import Any

from outpost import trace
from outpost.config import Settings, settings
from outpost.db import connect
from outpost.llm import OllamaClient, OllamaError

UNMAPPED_CODE = "unmapped"
MIN_CONFIDENCE = 0.30

# Cut-line fallback (BUILD_PLAN 15:00 gate): if retrieval is unavailable, these
# keywords still map the demo cases.
KEYWORD_MAP: dict[str, tuple[str, ...]] = {
    "acute_watery_diarrhoea": (
        "watery stool",
        "watery stools",
        "diarrhoea",
        "diarrhea",
        "rice water",
        "dehydration",
        "vomiting",
    ),
    "acute_respiratory_infection": (
        "cough",
        "shortness of breath",
        "difficulty breathing",
        "sore throat",
        "chest pain",
        "sputum",
    ),
    "acute_febrile_illness": (
        "fever",
        "febrile",
        "chills",
        "headache",
        "body ache",
        "malaise",
    ),
    "acute_jaundice_syndrome": ("jaundice", "yellow eyes", "dark urine", "hepatitis"),
    "acute_haemorrhagic_fever": (
        "bleeding",
        "haemorrhage",
        "hemorrhage",
        "bloody",
        "petechiae",
    ),
    "acute_bloody_diarrhoea": ("bloody stool", "blood in stool", "dysentery"),
}


@dataclass(frozen=True)
class SyndromeMatch:
    """Result of mapping a presentation to a case definition."""

    code: str
    confidence: float
    title: str = ""
    method: str = "embedding"

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "confidence": round(self.confidence, 4)}


def pack_vector(vector: list[float]) -> bytes:
    return array.array("f", vector).tobytes()


def unpack_vector(blob: bytes) -> list[float]:
    values = array.array("f")
    values.frombytes(blob)
    return list(values)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def upsert_definition(
    code: str,
    title: str,
    definition: str,
    source_note: str,
    *,
    client: OllamaClient | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> None:
    """Embed and store one case definition."""
    config = config or settings
    client = client or OllamaClient(config)

    # Embed title + definition together: the title carries the syndrome name and
    # the definition carries the symptoms, and queries can resemble either.
    vector = client.embed(config.embed_model, f"{title}. {definition}")

    owned = connection is None
    conn = connection or connect(config)
    try:
        conn.execute(
            "INSERT INTO case_definitions (code, title, definition, source_note,"
            " embedding) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(code) DO UPDATE SET title = excluded.title,"
            " definition = excluded.definition, source_note = excluded.source_note,"
            " embedding = excluded.embedding",
            (code, title, definition, source_note, pack_vector(vector)),
        )
    finally:
        if owned:
            conn.close()


def keyword_match(text: str) -> SyndromeMatch:
    """Deterministic fallback used when retrieval is unavailable."""
    lowered = (text or "").lower()
    best_code = UNMAPPED_CODE
    best_hits = 0

    for code, keywords in KEYWORD_MAP.items():
        hits = sum(1 for keyword in keywords if keyword in lowered)
        if hits > best_hits:
            best_code, best_hits = code, hits

    if best_hits == 0:
        return SyndromeMatch(UNMAPPED_CODE, 0.0, method="keyword")
    # Confidence is deliberately capped below the embedding path: this is a
    # coarse signal and should never outrank real retrieval.
    return SyndromeMatch(best_code, min(0.5, 0.2 + 0.1 * best_hits), method="keyword")


def map_presentation(
    text: str,
    *,
    client: OllamaClient | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> SyndromeMatch:
    """Return the best-matching case definition for a presentation."""
    config = config or settings
    if not text or not text.strip():
        return SyndromeMatch(UNMAPPED_CODE, 0.0, method="empty")

    owned = connection is None
    conn = connection or connect(config)
    try:
        rows = conn.execute(
            "SELECT code, title, embedding FROM case_definitions"
        ).fetchall()

        if not rows:
            return keyword_match(text)

        try:
            client = client or OllamaClient(config)
            query_vector = client.embed(config.embed_model, text)
        except OllamaError:
            return keyword_match(text)

        best: SyndromeMatch | None = None
        for row in rows:
            score = cosine_similarity(query_vector, unpack_vector(row["embedding"]))
            if best is None or score > best.confidence:
                best = SyndromeMatch(row["code"], score, row["title"])

        if best is None or best.confidence < MIN_CONFIDENCE:
            # Weak retrieval is worse than an honest "unmapped" — a wrong
            # syndrome code feeds straight into cluster detection.
            fallback = keyword_match(text)
            return fallback if fallback.code != UNMAPPED_CODE else SyndromeMatch(
                UNMAPPED_CODE, best.confidence if best else 0.0, method="below_threshold"
            )
        return best
    finally:
        if owned:
            conn.close()


def process(
    case_id: str,
    text: str,
    *,
    client: OllamaClient | None = None,
    connection: sqlite3.Connection | None = None,
    config: Settings | None = None,
) -> SyndromeMatch:
    """Map a presentation and persist it to ``artifacts``."""
    config = config or settings

    owned = connection is None
    conn = connection or connect(config)
    try:
        import time

        trace_id = trace.record(
            "worker:casedef",
            "map_presentation",
            {"case_id": case_id, "chars": len(text or "")},
            connection=conn,
        )
        started = time.perf_counter()
        match = map_presentation(text, client=client, connection=conn, config=config)

        # Keep the strongest mapping, never the most recent one. A case can
        # carry both a written note and a dictated recording; the recording goes
        # through ASR and translation, so its text is lossier and can retrieve a
        # weaker or plainly wrong syndrome. Overwriting unconditionally would let
        # the worse evidence win purely because it was processed second, and a
        # wrong syndrome code feeds straight into cluster detection.
        existing = conn.execute(
            "SELECT syndrome_code, syndrome_conf FROM artifacts WHERE case_id = ?",
            (case_id,),
        ).fetchone()
        previous_conf = (
            float(existing["syndrome_conf"])
            if existing is not None and existing["syndrome_conf"] is not None
            else -1.0
        )

        superseded = match.confidence <= previous_conf and previous_conf >= 0.0
        if superseded:
            trace.update(
                trace_id,
                result_summary=(
                    f"kept={existing['syndrome_code']} ({previous_conf:.3f}) "
                    f"over={match.code} ({match.confidence:.3f}) method={match.method}"
                ),
                duration_ms=int((time.perf_counter() - started) * 1000),
                connection=conn,
                config=config,
            )
            return SyndromeMatch(
                str(existing["syndrome_code"]), previous_conf, method="retained"
            )

        duration_ms = int((time.perf_counter() - started) * 1000)

        conn.execute(
            "INSERT INTO artifacts (case_id, syndrome_code, syndrome_conf, created_at)"
            " VALUES (?, ?, ?, datetime('now'))"
            " ON CONFLICT(case_id) DO UPDATE SET"
            " syndrome_code = excluded.syndrome_code,"
            " syndrome_conf = excluded.syndrome_conf",
            (case_id, match.code, match.confidence),
        )

        trace.update(
            trace_id,
            result_summary=(
                f"code={match.code} confidence={match.confidence:.3f} "
                f"method={match.method}"
            ),
            duration_ms=duration_ms,
            connection=conn,
        )
        return match
    finally:
        if owned:
            conn.close()


def definition_count(
    connection: sqlite3.Connection | None = None, config: Settings | None = None
) -> int:
    owned = connection is None
    conn = connection or connect(config or settings)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM case_definitions").fetchone()[0])
    finally:
        if owned:
            conn.close()
