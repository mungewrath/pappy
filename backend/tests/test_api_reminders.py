"""Reminder API tests — dashboard lifecycle + the test-send trigger."""

from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient


def _create_employer(client: TestClient) -> None:
    response = client.post(
        "/employers",
        json={
            "legal_name": "Jane Doe",
            "ein": "12-3456789",
            "address": {
                "line1": "1 Main St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98101",
            },
        },
    )
    assert response.status_code == 201, response.text


def _test_send(client: TestClient, **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {"rule": "WEEKLY_PAY", "send_email": False, **overrides}
    response = client.post("/reminders/test-send", json=body)
    assert response.status_code == 201, response.text
    result: dict[str, object] = response.json()
    return result


def test_list_is_empty_before_anything_fires(client: TestClient) -> None:
    response = client.get("/reminders")
    assert response.status_code == 200
    assert response.json() == []


def test_test_send_materializes_scoped_reminder(client: TestClient) -> None:
    _create_employer(client)
    result = _test_send(client, fire_date="2026-01-16")

    created = result["created"]
    assert isinstance(created, list) and len(created) == 1
    reminder = created[0]
    assert reminder["rule"] == "WEEKLY_PAY"
    assert reminder["due_date"] == "2026-01-16"
    assert reminder["status"] == "PENDING"  # send_email=False
    assert result["email_transport"] == "log"

    listed = client.get("/reminders").json()
    assert [r["due_date"] for r in listed] == ["2026-01-16"]


def test_acknowledge_flow_and_double_ack_conflict(client: TestClient) -> None:
    _create_employer(client)
    result = _test_send(client)

    reminder_id = f"{result['created'][0]['due_date']}:WEEKLY_PAY"  # type: ignore[index]
    acked = client.post(f"/reminders/{reminder_id}/acknowledge")
    assert acked.status_code == 200
    assert acked.json()["status"] == "ACKNOWLEDGED"

    # Acknowledged reminders drop out of the open set (they stop nagging).
    assert client.get("/reminders").json() == []
    history = client.get("/reminders?open_only=false").json()
    assert len(history) == 1

    conflict = client.post(f"/reminders/{reminder_id}/acknowledge")
    assert conflict.status_code == 409


def test_unknown_reminder_404s(client: TestClient) -> None:
    response = client.post("/reminders/2030-01-01:WEEKLY_PAY/acknowledge")
    assert response.status_code == 404


def test_test_send_is_idempotent_per_due_date(client: TestClient) -> None:
    _create_employer(client)
    first = _test_send(client, due_date="2026-04-15", rule="QUARTERLY_TAX")
    again = _test_send(client, due_date="2026-04-15", rule="QUARTERLY_TAX")

    assert len(first["created"]) == 1  # type: ignore[arg-type]
    assert again["created"] == []

    listed = client.get("/reminders?open_only=false").json()
    assert len(listed) == 1


def test_weekly_pay_with_drafts_creates_runs(client: TestClient) -> None:
    _create_employer(client)
    employee = client.post(
        "/employees",
        json={
            "full_name": "Nanny Smith",
            "address": {
                "line1": "2 Elm St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98102",
            },
            "hire_date": "2026-01-01",
            "hourly_rate": "25.00",
            "default_schedule": [{"weekday": d, "hours": "9"} for d in range(5)],
        },
    )
    assert employee.status_code == 201, employee.text

    result = _test_send(
        client,
        fire_date=date(2026, 1, 16).isoformat(),  # a Friday
        create_drafts=True,
    )

    runs = client.get("/payruns").json()
    assert len(runs) == 1
    run = runs[0]
    assert run["period_start"] == "2026-01-12" and run["pay_date"] == "2026-01-16"
    assert len(run["hour_lines"]) == 5
    created = result["created"]
    assert isinstance(created, list) and len(created) == 1
