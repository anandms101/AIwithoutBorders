"""Step 12 gate (F-10): counts only, under 1KB, one call site."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from outpost import egress
from outpost.config import Settings
from outpost.db import utcnow


def make_alert(db: sqlite3.Connection, alert_id: str = "alert-1", **overrides) -> dict:
    row = {
        "id": alert_id,
        "severity": "high",
        "syndrome_code": "acute_watery_diarrhoea",
        "catchment": "sector-4",
        "case_ids_json": json.dumps([f"case-{i}" for i in range(11)]),
        "window_hours": 72,
        "trend": "rising",
        "rationale_text": "11 cases matching acute watery diarrhoea — review recommended.",
        "created_at": utcnow(),
    }
    row.update(overrides)
    db.execute(
        "INSERT INTO alerts (id, severity, syndrome_code, catchment, case_ids_json,"
        " window_hours, trend, rationale_text, created_at)"
        " VALUES (:id, :severity, :syndrome_code, :catchment, :case_ids_json,"
        " :window_hours, :trend, :rationale_text, :created_at)",
        row,
    )
    return row


class TestPayloadContract:
    def test_has_exactly_six_fields(self) -> None:
        payload = egress.EgressPayload(
            "acute_watery_diarrhoea", "sector-4", 11, 72, "rising", "OP-001"
        )
        assert set(json.loads(payload.to_json())) == {
            "syndrome", "catchment", "count", "window_hours", "trend", "site_id"
        }

    def test_matches_the_architecture_example(self) -> None:
        payload = egress.EgressPayload(
            "acute_watery_diarrhoea", "sector-4", 11, 72, "rising", "OP-001"
        )
        assert json.loads(payload.to_json()) == {
            "syndrome": "acute_watery_diarrhoea",
            "catchment": "sector-4",
            "count": 11,
            "window_hours": 72,
            "trend": "rising",
            "site_id": "OP-001",
        }

    def test_is_under_one_kilobyte(self) -> None:
        payload = egress.EgressPayload(
            "acute_watery_diarrhoea", "sector-4", 11, 72, "rising", "OP-001"
        )
        assert payload.byte_size() < 1024
        payload.validate()

    def test_is_frozen(self) -> None:
        """No mutation between construction and send."""
        payload = egress.EgressPayload("a", "b", 1, 72, "rising", "OP-001")
        with pytest.raises(FrozenInstanceError):
            payload.syndrome = "changed"  # type: ignore[misc]

    def test_takes_no_kwargs(self) -> None:
        """A passthrough dict is how identifiers leak. The type forbids it."""
        with pytest.raises(TypeError):
            egress.EgressPayload(  # type: ignore[call-arg]
                "a", "b", 1, 72, "rising", "OP-001", case_id="case-1"
            )

    def test_oversize_payload_is_blocked(self) -> None:
        payload = egress.EgressPayload("x" * 2000, "sector-4", 1, 72, "rising", "OP-001")
        with pytest.raises(egress.EgressBlocked, match="limit"):
            payload.validate()

    def test_byte_size_is_stable(self) -> None:
        """The number goes on camera; it must be reproducible."""
        first = egress.EgressPayload("awd", "sector-4", 3, 72, "rising", "OP-001")
        second = egress.EgressPayload("awd", "sector-4", 3, 72, "rising", "OP-001")
        assert first.to_json() == second.to_json()


class TestNoIdentifiers:
    def test_case_ids_are_collapsed_to_a_count(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        alert = make_alert(db)
        payload = egress.payload_for_alert(alert, config=test_settings)

        assert payload.count == 11
        encoded = payload.to_json()
        for index in range(11):
            assert f"case-{index}" not in encoded

    def test_rationale_is_dropped(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        alert = make_alert(
            db, rationale_text="Patient Jean Dupont, age 41, profuse watery stools."
        )
        encoded = egress.payload_for_alert(alert, config=test_settings).to_json()

        for leak in ("Jean", "Dupont", "41", "watery stools"):
            assert leak not in encoded

    @pytest.mark.parametrize("forbidden", egress.FORBIDDEN_KEYS)
    def test_forbidden_keys_are_absent(
        self, db: sqlite3.Connection, test_settings: Settings, forbidden: str
    ) -> None:
        alert = make_alert(db)
        encoded = egress.payload_for_alert(alert, config=test_settings).to_json()
        assert f'"{forbidden}"' not in encoded.lower()

    def test_no_free_text_beyond_controlled_vocabulary(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        alert = make_alert(db)
        parsed = json.loads(
            egress.payload_for_alert(alert, config=test_settings).to_json()
        )
        assert parsed["trend"] in {"rising", "falling", "stable"}
        assert " " not in parsed["syndrome"]
        assert " " not in parsed["catchment"]


class TestSingleCallSite:
    def test_send_is_called_only_from_approve(self) -> None:
        """Invariant 3: nothing transmits without an explicit human Approve."""
        source = Path(egress.__file__).read_text()
        call_lines = [
            line.strip()
            for line in source.splitlines()
            if "send(" in line and "def send" not in line and not line.strip().startswith("#")
        ]
        assert len(call_lines) == 1, f"expected one call site, found: {call_lines}"

    def test_no_other_module_calls_send(self) -> None:
        root = Path(egress.__file__).parent
        offenders = []
        for path in root.rglob("*.py"):
            if path.name == "egress.py":
                continue
            text = path.read_text()
            if "egress.send(" in text:
                offenders.append(path.name)
        assert offenders == [], f"egress.send called outside egress.py: {offenders}"


class TestApproveDismiss:
    def test_approve_transmits_and_records_bytes(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        make_alert(db)
        sent: list[int] = []
        monkeypatch.setattr(
            egress, "send", lambda p, **k: sent.append(p.byte_size()) or p.byte_size()
        )

        size = egress.approve_alert("alert-1", connection=db, config=test_settings)

        assert size > 0 and len(sent) == 1
        row = db.execute("SELECT * FROM alerts WHERE id='alert-1'").fetchone()
        assert row["status"] == "approved"
        assert row["bytes_sent"] == size
        assert row["decided_at"]

    def test_dismiss_transmits_nothing(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        make_alert(db)
        monkeypatch.setattr(
            egress, "send", lambda *a, **k: pytest.fail("dismiss must not transmit")
        )

        assert egress.dismiss_alert("alert-1", connection=db, config=test_settings)
        row = db.execute("SELECT * FROM alerts WHERE id='alert-1'").fetchone()
        assert row["status"] == "dismissed"
        assert row["bytes_sent"] is None

    def test_cannot_approve_twice(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        make_alert(db)
        monkeypatch.setattr(egress, "send", lambda p, **k: p.byte_size())
        egress.approve_alert("alert-1", connection=db, config=test_settings)

        with pytest.raises(egress.EgressBlocked, match="no pending alert"):
            egress.approve_alert("alert-1", connection=db, config=test_settings)

    def test_cannot_approve_unknown_alert(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        with pytest.raises(egress.EgressBlocked, match="no pending alert"):
            egress.approve_alert("nope", connection=db, config=test_settings)


class TestByteCounters:
    def test_bytes_sent_starts_at_zero(
        self, db: sqlite3.Connection, test_settings: Settings
    ) -> None:
        assert egress.bytes_sent(connection=db, config=test_settings) == 0

    def test_bytes_on_box_dwarfs_bytes_sent(
        self, db: sqlite3.Connection, test_settings: Settings, monkeypatch
    ) -> None:
        """The comparison is the pitch."""
        db.execute(
            "INSERT INTO artifacts (case_id, native_transcript, english_text,"
            " film_findings, created_at) VALUES ('c1', ?, ?, ?, datetime('now'))",
            ("le patient rapporte " * 200, "the patient reports " * 200, "opacity" * 50),
        )
        make_alert(db)
        monkeypatch.setattr(egress, "send", lambda p, **k: p.byte_size())
        egress.approve_alert("alert-1", connection=db, config=test_settings)

        on_box = egress.bytes_on_box(connection=db, config=test_settings)
        out = egress.bytes_sent(connection=db, config=test_settings)

        assert out < 1024
        assert on_box > out * 10


class TestMockReceiver:
    def test_rejects_unexpected_fields(self) -> None:
        from fastapi.testclient import TestClient

        from mock_receiver import app

        client = TestClient(app)
        response = client.post(
            "/report",
            content=json.dumps({
                "syndrome": "awd", "catchment": "sector-4", "count": 3,
                "window_hours": 72, "trend": "rising", "site_id": "OP-001",
                "case_id": "case-1",
            }),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422
        assert "case_id" in response.json()["error"]

    def test_accepts_the_contract_payload(self) -> None:
        from fastapi.testclient import TestClient

        from mock_receiver import app

        client = TestClient(app)
        payload = egress.EgressPayload(
            "acute_watery_diarrhoea", "sector-4", 11, 72, "rising", "OP-001"
        )
        response = client.post(
            "/report",
            content=payload.to_json(),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 200
        assert response.json()["bytes"] == payload.byte_size()
