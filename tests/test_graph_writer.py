"""Step 8 gate (F-05): nodes, edges, and the denormalised surveillance view."""

from __future__ import annotations

import sqlite3

import pytest

from outpost.config import Settings
from outpost.workers import graph_writer as gw


def test_one_case_writes_three_nodes_two_edges(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    result = gw.write_case(
        "case-0421", "p-014", "acute_watery_diarrhoea", "sector-4",
        connection=db, config=test_settings,
    )

    assert result.nodes_written == 3
    assert result.edges_written == 2

    nodes = {r["id"]: r["type"] for r in db.execute("SELECT id, type FROM nodes")}
    assert nodes == {
        "patient:p-014": "patient",
        "visit:case-0421": "visit",
        "syndrome:acute_watery_diarrhoea": "syndrome",
    }

    edges = {(r["src"], r["dst"], r["rel"]) for r in db.execute("SELECT * FROM edges")}
    assert edges == {
        ("patient:p-014", "visit:case-0421", "had_visit"),
        ("visit:case-0421", "syndrome:acute_watery_diarrhoea", "presented_as"),
    }

    cases = db.execute("SELECT * FROM cases").fetchall()
    assert len(cases) == 1
    assert cases[0]["syndrome_code"] == "acute_watery_diarrhoea"
    assert cases[0]["catchment"] == "sector-4"


def test_reprocessing_is_idempotent(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """A file dropped twice must not double-count into a cluster."""
    for _ in range(3):
        gw.write_case(
            "case-0421", "p-014", "acute_watery_diarrhoea", "sector-4",
            connection=db, config=test_settings,
        )

    assert db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
    assert db.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 2
    assert db.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1


def test_second_visit_reuses_patient_node(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    first = gw.write_case(
        "case-1", "p-014", "acute_febrile_illness", "sector-4",
        connection=db, config=test_settings,
    )
    second = gw.write_case(
        "case-2", "p-014", "acute_watery_diarrhoea", "sector-4",
        connection=db, config=test_settings,
    )

    assert first.nodes_written == 3
    assert second.nodes_written == 2, "patient node already existed"

    patients = db.execute("SELECT COUNT(*) FROM nodes WHERE type='patient'").fetchone()[0]
    assert patients == 1

    visits = db.execute(
        "SELECT COUNT(*) FROM edges WHERE src='patient:p-014' AND rel='had_visit'"
    ).fetchone()[0]
    assert visits == 2


def test_shared_syndrome_node_across_patients(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """The cluster shape: many patients presenting as one syndrome."""
    for index in range(3):
        gw.write_case(
            f"case-{index}", f"p-{index}", "acute_watery_diarrhoea", "sector-4",
            connection=db, config=test_settings,
        )

    syndromes = db.execute(
        "SELECT COUNT(*) FROM nodes WHERE type='syndrome'"
    ).fetchone()[0]
    assert syndromes == 1

    presented = db.execute(
        "SELECT COUNT(*) FROM edges WHERE dst='syndrome:acute_watery_diarrhoea'"
    ).fetchone()[0]
    assert presented == 3


def test_cases_row_updates_on_rewrite(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    gw.write_case(
        "case-1", "p-1", "acute_febrile_illness", "sector-4",
        film_score=20, connection=db, config=test_settings,
    )
    gw.write_case(
        "case-1", "p-1", "acute_respiratory_infection", "sector-9",
        film_score=88, connection=db, config=test_settings,
    )

    row = db.execute("SELECT * FROM cases WHERE case_id='case-1'").fetchone()
    assert row["syndrome_code"] == "acute_respiratory_infection"
    assert row["catchment"] == "sector-9"
    assert row["film_score"] == 88


def test_write_is_traced(db: sqlite3.Connection, test_settings: Settings) -> None:
    gw.write_case(
        "case-1", "p-1", "acute_watery_diarrhoea", "sector-4",
        connection=db, config=test_settings,
    )
    rows = db.execute(
        "SELECT tool, result_summary FROM trace WHERE actor='worker:graph'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["tool"] == "write_case"
    assert "acute_watery_diarrhoea" in rows[0]["result_summary"]


def test_write_from_artifacts_promotes_structured_fields_only(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    """Invariant 5: free text must not cross into the surveillance view."""
    db.execute(
        "INSERT INTO artifacts (case_id, syndrome_code, film_score, english_text,"
        " native_transcript, film_findings, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            "case-0421",
            "acute_watery_diarrhoea",
            73,
            "patient reports profuse watery stools",
            "le patient rapporte des selles liquides",
            "patchy consolidation",
        ),
    )

    result = gw.write_from_artifacts(
        "case-0421", "p-014", "sector-4", connection=db, config=test_settings
    )
    assert result is not None
    assert result.syndrome_code == "acute_watery_diarrhoea"

    row = db.execute("SELECT * FROM cases WHERE case_id='case-0421'").fetchone()
    assert row["film_score"] == 73

    # The cases table has no column that could carry narrative text at all.
    columns = {description[0] for description in db.execute("SELECT * FROM cases").description}
    assert columns == {
        "case_id", "patient_id", "syndrome_code", "catchment", "film_score", "occurred_at"
    }
    assert "english_text" not in columns
    assert "film_findings" not in columns


def test_write_from_artifacts_skips_unmapped(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    db.execute(
        "INSERT INTO artifacts (case_id, created_at) VALUES ('case-x', datetime('now'))"
    )
    assert gw.write_from_artifacts(
        "case-x", "p-1", "sector-4", connection=db, config=test_settings
    ) is None
    assert gw.case_count(connection=db) == 0


def test_missing_artifacts_row_returns_none(
    db: sqlite3.Connection, test_settings: Settings
) -> None:
    assert gw.write_from_artifacts(
        "absent", "p-1", "sector-4", connection=db, config=test_settings
    ) is None


@pytest.mark.parametrize(
    ("helper", "value", "expected"),
    [
        (gw.patient_node_id, "p-014", "patient:p-014"),
        (gw.visit_node_id, "v-221", "visit:v-221"),
        (gw.syndrome_node_id, "awd", "syndrome:awd"),
    ],
)
def test_node_id_helpers(helper, value: str, expected: str) -> None:
    assert helper(value) == expected
