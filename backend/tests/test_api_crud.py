"""End-to-end CRUD tests through the FastAPI app, backed by moto DynamoDB.

The app derives `employerId` from the JWT `sub` claim (design-doc.md §7.1);
the default test client authenticates as `DEFAULT_SUB`, and tests that care
about identity scoping send explicit `Authorization` headers via
`auth_headers(sub)`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient


def _create_employer(client: TestClient) -> dict[str, Any]:
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
    result: dict[str, Any] = response.json()
    return result


def _create_employee(client: TestClient) -> dict[str, Any]:
    response = client.post(
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
            "overtime_policy": "APPLIES",
            "default_schedule": [
                {"weekday": 0, "hours": "9"},
                {"weekday": 1, "hours": "9"},
                {"weekday": 2, "hours": "9"},
                {"weekday": 3, "hours": "9"},
                {"weekday": 4, "hours": "9"},
            ],
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def _open_draft(client: TestClient, employee_id: str) -> dict[str, Any]:
    response = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
        },
    )
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_unauthenticated_requests_are_rejected(client: TestClient) -> None:
    for method, path in (
        ("GET", "/employers"),
        ("GET", "/employees"),
        ("GET", "/payruns"),
    ):
        response = client.request(method, path, headers={"Authorization": ""})
        assert response.status_code == 401, f"{method} {path}: {response.text}"

    no_token = client.get("/employees", headers={"Authorization": "Bearer not-a-jwt"})
    assert no_token.status_code == 401


def test_dev_fallback_sub_is_used_without_a_token(
    client: TestClient, monkeypatch: Any
) -> None:
    """PAPPY_DEV_FALLBACK_SUB pins unauthenticated local requests to one
    principal — the docker-compose escape hatch for Cognito-less dev."""
    monkeypatch.setenv("PAPPY_DEV_FALLBACK_SUB", "dev-user-sub")

    created = client.post(
        "/employers",
        headers={"Authorization": ""},  # no token at all
        json={
            "legal_name": "Dev User",
            "ein": "12-3456789",
            "address": {
                "line1": "1 Main St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98101",
            },
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["employer_id"] == "dev-user-sub"

    # A real token still wins over the fallback.
    assert client.get("/employers").status_code == 404


def test_employer_crud(client: TestClient) -> None:
    employer = _create_employer(client)
    employer_id = employer["employer_id"]

    fetched = client.get("/employers")
    assert fetched.status_code == 200
    assert fetched.json()["legal_name"] == "Jane Doe"

    updated = client.patch("/employers", json={"ubi": "600123456"})
    assert updated.status_code == 200
    assert updated.json()["ubi"] == "600123456"
    assert updated.json()["legal_name"] == "Jane Doe"

    # The profile is keyed by the token's `sub`, and creation is idempotent:
    # re-posting returns the existing profile unchanged (200, same id).
    again = client.post(
        "/employers",
        json={
            "legal_name": "Someone Else",
            "ein": "99-9999999",
            "address": {
                "line1": "1 Main St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98101",
            },
        },
    )
    assert again.status_code == 200, again.text
    assert again.json()["employer_id"] == employer_id
    assert again.json()["legal_name"] == "Jane Doe"


def test_data_is_scoped_by_sub(
    client: TestClient, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    """Another authenticated principal must see none of this user's data."""
    _create_employer(client)
    employee = _create_employee(client)

    other = auth_headers("someone-else-sub")
    assert client.get("/employers", headers=other).status_code == 404
    assert client.get("/employees", headers=other).json() == []

    # Writes through someone else's identity land in their own partition...
    assert client.post(
        "/employers",
        headers=other,
        json={
            "legal_name": "Someone Else",
            "ein": "99-9999999",
            "address": {
                "line1": "3 Oak St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98103",
            },
        },
    ).status_code == 201, "other user onboards into their own partition"
    other_employee = client.post(
        "/employees",
        headers=other,
        json={
            "full_name": "Invisible Nanny",
            "address": {
                "line1": "3 Oak St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98103",
            },
            "hire_date": "2026-01-01",
            "hourly_rate": "30.00",
        },
    )
    assert other_employee.status_code == 201, other_employee.text

    # ...and cannot touch this user's employee by guessing its ID.
    poached = client.get(
        f"/employees/{employee['employee_id']}", headers=other
    )
    assert poached.status_code == 404

    # Each partition is independent and invisible to the other.
    mine = client.get("/employees")
    assert [e["full_name"] for e in mine.json()] == ["Nanny Smith"]
    theirs = client.get("/employees", headers=other)
    assert [e["full_name"] for e in theirs.json()] == ["Invisible Nanny"]


def test_employee_crud(client: TestClient) -> None:
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]
    assert employee["hourly_rate"] == "25.00"

    listed = client.get("/employees")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/employees/{employee_id}")
    assert fetched.status_code == 200

    updated = client.patch(f"/employees/{employee_id}", json={"hourly_rate": "27.50"})
    assert updated.status_code == 200
    assert updated.json()["hourly_rate"] == "27.50"

    deleted = client.delete(f"/employees/{employee_id}")
    assert deleted.status_code == 204

    gone = client.get(f"/employees/{employee_id}")
    assert gone.status_code == 404


def test_employee_create_requires_existing_employer(client: TestClient) -> None:
    response = client.post(
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
        },
    )
    assert response.status_code == 404


def test_payrun_lifecycle_draft_edit_finalize(client: TestClient, seeded_rates: object) -> None:
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]

    # a W-4 election is required input for finalization (design-doc.md §5.3)
    w4 = client.post(
        f"/employees/{employee_id}/w4",
        json={"effective_date": "2026-01-01", "filing_status": "SINGLE_OR_MFS"},
    )
    assert w4.status_code == 201, w4.text
    listed_w4 = client.get(f"/employees/{employee_id}/w4")
    assert listed_w4.status_code == 200
    assert len(listed_w4.json()) == 1

    created = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["run_id"]

    # auto-populated from the 5x9 default schedule = 45 hours -> 5 OT hours
    assert run["status"] == "DRAFT"
    assert run["gross"]["regular_hours"] == "45"
    assert run["gross"]["overtime_hours"] == "5"
    assert run["gross"]["gross"] == "1187.50"
    assert run["payroll"] is None

    listed = client.get("/payruns")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/payruns/{run_id}")
    assert fetched.status_code == 200

    # employer edits hours: add a sick day for one of the days
    edited = client.put(
        f"/payruns/{run_id}/hours",
        json={
            "hour_lines": [
                {"work_date": "2026-01-05", "hours": "8", "category": "REGULAR"},
                {"work_date": "2026-01-06", "hours": "8", "category": "SICK"},
            ]
        },
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["gross"]["regular_hours"] == "8"
    assert edited.json()["gross"]["other_paid_hours"] == "8"
    assert edited.json()["gross"]["gross"] == "400.00"

    finalized = client.post(
        f"/payruns/{run_id}/finalize",
        json={},
    )
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["status"] == "FINALIZED"
    # rate table version resolved server-side from RATES#2026
    assert body["rate_table_version"] == 1
    payroll = body["payroll"]
    assert payroll is not None
    # $400 gross: SS $24.80, Medicare $5.80, FIT ($20,800 annualized less the
    # $8,600 offset -> $12,200 -> 10% bracket above $7,500 = $470/yr ->
    # $9.04), PFML $3.23, WA Cares $2.32; net = $354.81
    assert payroll["withholding"]["social_security"] == "24.80"
    assert payroll["withholding"]["medicare"] == "5.80"
    assert payroll["withholding"]["federal_income_tax"] == "9.04"
    assert payroll["net_pay"] == "354.81"

    # can no longer edit hours on a finalized run
    blocked = client.put(
        f"/payruns/{run_id}/hours",
        json={"hour_lines": [{"work_date": "2026-01-05", "hours": "1"}]},
    )
    assert blocked.status_code == 409

    # can't finalize twice
    blocked_again = client.post(f"/payruns/{run_id}/finalize", json={})
    assert blocked_again.status_code == 409


def test_finalize_without_w4_is_blocked(client: TestClient, seeded_rates: object) -> None:
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]

    created = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    blocked = client.post(f"/payruns/{run_id}/finalize", json={})
    assert blocked.status_code == 409
    assert "W-4" in blocked.json()["detail"]


def test_finalize_without_rate_table_is_blocked(client: TestClient) -> None:
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]
    client.post(
        f"/employees/{employee_id}/w4",
        json={"effective_date": "2026-01-01"},
    )

    created = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
        },
    )
    assert created.status_code == 201
    run_id = created.json()["run_id"]

    blocked = client.post(f"/payruns/{run_id}/finalize", json={})
    assert blocked.status_code == 404


def test_payrun_create_with_explicit_hours(client: TestClient) -> None:
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]

    created = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
            "hour_lines": [{"work_date": "2026-01-05", "hours": "10"}],
        },
    )
    assert created.status_code == 201
    assert created.json()["gross"]["gross"] == "250.00"
