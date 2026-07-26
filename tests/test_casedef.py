"""Step 6 gate (F-04): retrieval maps presentations to case definitions."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from outpost.case_definitions_data import CASE_DEFINITIONS, DISCLAIMER, all_codes
from outpost.config import Settings
from outpost.llm import OllamaError
from outpost.workers import casedef


class FakeEmbedClient:
    """Deterministic stand-in so retrieval logic is testable without a model."""

    def __init__(self, vectors: dict[str, list[float]], error: Exception | None = None):
        self.vectors = vectors
        self.error = error

    def embed(self, model: str, text: str) -> list[float]:
        if self.error:
            raise self.error
        for key, vector in self.vectors.items():
            if key in text:
                return vector
        return [0.0, 0.0, 1.0]


def test_vector_roundtrip() -> None:
    original = [0.5, -0.25, 1.0, 0.0]
    restored = casedef.unpack_vector(casedef.pack_vector(original))
    assert restored == pytest.approx(original)


@pytest.mark.parametrize(
    ("left", "right", "expected"),
    [
        ([1.0, 0.0], [1.0, 0.0], 1.0),
        ([1.0, 0.0], [0.0, 1.0], 0.0),
        ([1.0, 0.0], [-1.0, 0.0], -1.0),
        ([0.0, 0.0], [1.0, 0.0], 0.0),
        ([1.0, 0.0], [], 0.0),
        ([1.0, 0.0], [1.0, 0.0, 0.0], 0.0),
    ],
)
def test_cosine_similarity(left: list, right: list, expected: float) -> None:
    assert casedef.cosine_similarity(left, right) == pytest.approx(expected)


def test_top_one_match_is_returned(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    client = FakeEmbedClient(
        {
            "Acute watery diarrhoea": [1.0, 0.0, 0.0],
            "Acute respiratory infection": [0.0, 1.0, 0.0],
            "watery stools": [0.95, 0.1, 0.0],
        }
    )
    for code, title, definition in (
        ("acute_watery_diarrhoea", "Acute watery diarrhoea", "loose stools"),
        ("acute_respiratory_infection", "Acute respiratory infection", "cough"),
    ):
        casedef.upsert_definition(
            code, title, definition, DISCLAIMER,
            client=client, connection=db, config=test_settings,
        )

    match = casedef.map_presentation(
        "profuse watery stools", client=client, connection=db, config=test_settings
    )
    assert match.code == "acute_watery_diarrhoea"
    assert match.method == "embedding"
    assert match.confidence > casedef.MIN_CONFIDENCE


def test_upsert_replaces_not_duplicates(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    client = FakeEmbedClient({"x": [1.0, 0.0, 0.0]})
    for title in ("First title", "Second title"):
        casedef.upsert_definition(
            "code_a", title, "x", DISCLAIMER,
            client=client, connection=db, config=test_settings,
        )

    rows = db.execute("SELECT title FROM case_definitions").fetchall()
    assert len(rows) == 1
    assert rows[0]["title"] == "Second title"


def test_empty_text_is_unmapped(db: sqlite3.Connection, test_settings: Settings) -> None:
    for text in ("", "   "):
        match = casedef.map_presentation(text, connection=db, config=test_settings)
        assert match.code == casedef.UNMAPPED_CODE
        assert match.confidence == 0.0


def test_falls_back_to_keywords_when_model_errors(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """BUILD_PLAN 15:00 cut line: drop RAG, keep the demo working."""
    seed = FakeEmbedClient({"": [1.0, 0.0, 0.0]})
    casedef.upsert_definition(
        "acute_watery_diarrhoea", "Acute watery diarrhoea", "loose stools",
        DISCLAIMER, client=seed, connection=db, config=test_settings,
    )

    broken = FakeEmbedClient({}, error=OllamaError("down"))
    match = casedef.map_presentation(
        "profuse watery stools with dehydration",
        client=broken, connection=db, config=test_settings,
    )
    assert match.code == "acute_watery_diarrhoea"
    assert match.method == "keyword"


def test_falls_back_when_no_definitions_seeded(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    match = casedef.map_presentation(
        "watery stools and dehydration", connection=db, config=test_settings
    )
    assert match.code == "acute_watery_diarrhoea"
    assert match.method == "keyword"


def test_keyword_confidence_never_outranks_embedding() -> None:
    """A coarse signal must not beat real retrieval."""
    match = casedef.keyword_match("watery stools diarrhoea dehydration vomiting")
    assert match.confidence <= 0.5


def test_keyword_no_hits_is_unmapped() -> None:
    match = casedef.keyword_match("routine follow up, no complaints")
    assert match.code == casedef.UNMAPPED_CODE
    assert match.confidence == 0.0


def test_weak_similarity_does_not_invent_a_syndrome(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """A wrong code feeds straight into cluster detection — refuse instead."""
    client = FakeEmbedClient(
        {
            "Acute watery diarrhoea": [1.0, 0.0, 0.0],
            "unrelated": [0.0, 0.0, 1.0],
        }
    )
    casedef.upsert_definition(
        "acute_watery_diarrhoea", "Acute watery diarrhoea", "loose stools",
        DISCLAIMER, client=client, connection=db, config=test_settings,
    )

    match = casedef.map_presentation(
        "unrelated administrative note", client=client, connection=db, config=test_settings
    )
    assert match.code == casedef.UNMAPPED_CODE


def test_process_persists_and_traces(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    client = FakeEmbedClient({"Acute watery diarrhoea": [1.0, 0.0, 0.0],
                              "watery": [1.0, 0.0, 0.0]})
    casedef.upsert_definition(
        "acute_watery_diarrhoea", "Acute watery diarrhoea", "loose stools",
        DISCLAIMER, client=client, connection=db, config=test_settings,
    )

    casedef.process(
        "case-0421", "watery stools", client=client, connection=db, config=test_settings
    )

    row = db.execute(
        "SELECT syndrome_code, syndrome_conf FROM artifacts WHERE case_id = ?",
        ("case-0421",),
    ).fetchone()
    assert row["syndrome_code"] == "acute_watery_diarrhoea"
    assert row["syndrome_conf"] > 0

    traced = db.execute(
        "SELECT tool, result_summary FROM trace WHERE actor = 'worker:casedef'"
    ).fetchall()
    assert len(traced) == 1
    assert "acute_watery_diarrhoea" in traced[0]["result_summary"]


class TestStrongestMappingWins:
    """A case can carry both a note and a dictated recording.

    ASR text is lossier, so it must not overwrite a better note-derived
    mapping purely by being processed second. Found live: Whisper rendered
    "selles liquides" as "liquid salts", which retrieved acute_febrile_illness
    over acute_watery_diarrhoea and silently broke cluster detection.
    """

    def _seed(self, db: sqlite3.Connection, test_settings: Settings) -> FakeEmbedClient:
        client = FakeEmbedClient(
            {
                "Acute watery diarrhoea": [1.0, 0.0, 0.0],
                "Acute febrile illness": [0.0, 1.0, 0.0],
                "watery stools": [1.0, 0.0, 0.0],
                "liquid salts": [0.55, 0.83, 0.0],
            }
        )
        for code, title in (
            ("acute_watery_diarrhoea", "Acute watery diarrhoea"),
            ("acute_febrile_illness", "Acute febrile illness"),
        ):
            casedef.upsert_definition(
                code, title, "definition text", DISCLAIMER,
                client=client, connection=db, config=test_settings,
            )
        return client

    def test_weaker_later_mapping_does_not_overwrite(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        client = self._seed(db, test_settings)

        first = casedef.process(
            "case-1", "watery stools", client=client, connection=db, config=test_settings
        )
        second = casedef.process(
            "case-1", "liquid salts", client=client, connection=db, config=test_settings
        )

        assert first.code == "acute_watery_diarrhoea"
        assert second.code == "acute_watery_diarrhoea", "weaker mapping must not win"
        assert second.method == "retained"

        row = db.execute(
            "SELECT syndrome_code FROM artifacts WHERE case_id = 'case-1'"
        ).fetchone()
        assert row["syndrome_code"] == "acute_watery_diarrhoea"

    def test_stronger_later_mapping_does_overwrite(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        client = self._seed(db, test_settings)

        casedef.process(
            "case-2", "liquid salts", client=client, connection=db, config=test_settings
        )
        second = casedef.process(
            "case-2", "watery stools", client=client, connection=db, config=test_settings
        )

        assert second.code == "acute_watery_diarrhoea"
        assert second.method == "embedding"

    def test_retention_is_traced(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        """The panel must show why the second mapping was discarded."""
        client = self._seed(db, test_settings)
        casedef.process(
            "case-3", "watery stools", client=client, connection=db, config=test_settings
        )
        casedef.process(
            "case-3", "liquid salts", client=client, connection=db, config=test_settings
        )

        summaries = [
            row["result_summary"]
            for row in db.execute(
                "SELECT result_summary FROM trace WHERE actor = 'worker:casedef'"
            ).fetchall()
        ]
        assert any(s and s.startswith("kept=") for s in summaries)


class TestCaseDefinitionData:
    """D14 clearance requirements are testable, so test them."""

    def test_codes_are_unique(self) -> None:
        codes = all_codes()
        assert len(codes) == len(set(codes))
        assert len(codes) >= 8

    def test_disclaimer_carries_who_adaptation_notice(self) -> None:
        lowered = DISCLAIMER.lower()
        assert "who" in lowered
        assert "not endorsed by who" in lowered
        assert "calibrated per setting" in lowered

    def test_definitions_are_populated(self) -> None:
        for code, title, definition in CASE_DEFINITIONS:
            assert code and title and definition
            assert len(definition) > 40, f"{code} definition looks truncated"


@pytest.mark.live
class TestLiveRetrieval:
    """Real embeddinggemma retrieval over the real seeded definitions."""

    @pytest.fixture
    def seeded(self, db: sqlite3.Connection, test_settings: Settings) -> Any:
        from outpost.llm import OllamaClient

        client = OllamaClient(test_settings)
        if not client.health():
            pytest.skip("Ollama not reachable")
        for code, title, definition in CASE_DEFINITIONS:
            casedef.upsert_definition(
                code, title, definition, DISCLAIMER,
                client=client, connection=db, config=test_settings,
            )
        return client

    @pytest.mark.parametrize(
        ("presentation", "expected"),
        [
            ("profuse watery stools, dehydration", "acute_watery_diarrhoea"),
            ("cough and difficulty breathing for three days", "acute_respiratory_infection"),
            ("yellow eyes and dark urine", "acute_jaundice_syndrome"),
            ("blood in the stool with cramps", "acute_bloody_diarrhoea"),
            ("cough for three weeks with night sweats and weight loss", "suspected_tuberculosis"),
        ],
    )
    def test_retrieves_expected_syndrome(
        self,
        seeded: Any,
        db: sqlite3.Connection,
        test_settings: Settings,
        presentation: str,
        expected: str,
    ) -> None:
        match = casedef.map_presentation(
            presentation, client=seeded, connection=db, config=test_settings
        )
        assert match.code == expected, f"got {match.code} @ {match.confidence:.3f}"
        assert match.method == "embedding"

    def test_embedding_dimensions(self, seeded: Any, test_settings: Settings) -> None:
        vector = seeded.embed(test_settings.embed_model, "fever")
        assert len(vector) == 768
