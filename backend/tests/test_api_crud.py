"""End-to-end CRUD tests through the FastAPI app, backed by moto DynamoDB.

The app derives `employerId` from the JWT `sub` claim (design-doc.md §7.1);
the default test client authenticates as `DEFAULT_SUB`, and tests that care
about identity scoping send explicit `Authorization` headers via
`auth_headers(sub)`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pappy.models.payrun import ExtraPayLine


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
    assert run["gross"]["extra_pay"] == "0.00"
    assert run["gross"]["gross"] == "1187.50"
    assert run["extra_pay_lines"] == []
    assert run["payroll"] is None

    listed = client.get("/payruns")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = client.get(f"/payruns/{run_id}")
    assert fetched.status_code == 200

    # employer edits hours: add a sick day for one of the days
    edited = client.put(
        f"/payruns/{run_id}",
        json={
            "hour_lines": [
                {"work_date": "2026-01-05", "hours": "8", "category": "REGULAR"},
                {"work_date": "2026-01-06", "hours": "8", "category": "SICK"},
            ],
            "extra_pay_lines": [],
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

    # can no longer edit a finalized run
    blocked = client.put(
        f"/payruns/{run_id}",
        json={
            "hour_lines": [{"work_date": "2026-01-05", "hours": "1"}],
            "extra_pay_lines": [],
        },
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


def test_draft_payrun_delete(client: TestClient, seeded_rates: object) -> None:
    """Drafts are disposable; finalized runs never are (§3.2)."""
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]
    client.post(
        f"/employees/{employee_id}/w4",
        json={"effective_date": "2026-01-01", "filing_status": "SINGLE_OR_MFS"},
    )

    keep = _open_draft(client, employee_id)
    doomed = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-12",
            "period_end": "2026-01-18",
            "pay_date": "2026-01-23",
        },
    )
    assert doomed.status_code == 201, doomed.text

    deleted = client.delete(f"/payruns/{doomed.json()['run_id']}")
    assert deleted.status_code == 204

    assert client.get(f"/payruns/{doomed.json()['run_id']}").status_code == 404
    assert [run["run_id"] for run in client.get("/payruns").json()] == [keep["run_id"]]

    # gone for good — a second delete 404s rather than pretending to succeed
    assert client.delete(f"/payruns/{doomed.json()['run_id']}").status_code == 404

    # a finalized run is immutable history, not a draft
    finalized = client.post(f"/payruns/{keep['run_id']}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    blocked = client.delete(f"/payruns/{keep['run_id']}")
    assert blocked.status_code == 409
    assert "FINALIZED" in blocked.json()["detail"]
    assert client.get(f"/payruns/{keep['run_id']}").status_code == 200


def test_draft_payrun_delete_is_employer_scoped(
    client: TestClient, auth_headers: Callable[[str], dict[str, str]]
) -> None:
    _create_employer(client)
    employee_id = _create_employee(client)["employee_id"]
    run = _open_draft(client, employee_id)

    other = auth_headers("someone-else-sub")
    assert client.delete(f"/payruns/{run['run_id']}", headers=other).status_code == 404
    assert client.get(f"/payruns/{run['run_id']}").status_code == 200


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


def test_payrun_extra_pay_line(client: TestClient, seeded_rates: object) -> None:
    """A flat lump sum on a draft: gross, withholding, and the reports layer."""
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]
    client.post(
        f"/employees/{employee_id}/w4",
        json={"effective_date": "2026-01-01", "filing_status": "SINGLE_OR_MFS"},
    )

    created = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
            "extra_pay_lines": [{"note": "Holiday bonus", "amount": "250.00"}],
        },
    )
    assert created.status_code == 201, created.text
    run = created.json()
    run_id = run["run_id"]

    # 45 auto-seeded hours -> $1,187.50 hours pay, plus the flat $250
    assert run["extra_pay_lines"][0]["note"] == "Holiday bonus"
    assert run["extra_pay_lines"][0]["amount"] == "250.00"
    assert run["gross"]["extra_pay"] == "250.00"
    assert run["gross"]["gross"] == "1437.50"

    # amounts round-trip as decimal strings, never floats
    reloaded = client.get(f"/payruns/{run_id}")
    assert reloaded.status_code == 200
    assert reloaded.json()["extra_pay_lines"][0]["amount"] == "250.00"

    # several lines sum into one gross line
    multi = client.put(
        f"/payruns/{run_id}",
        json={
            "hour_lines": run["hour_lines"],
            "extra_pay_lines": [
                {"note": "Holiday bonus", "amount": "250.00"},
                {"note": "Referral thank-you", "amount": "100.50"},
            ],
        },
    )
    assert multi.status_code == 200, multi.text
    assert multi.json()["gross"]["extra_pay"] == "350.50"
    assert multi.json()["gross"]["gross"] == "1538.00"

    finalized = client.post(f"/payruns/{run_id}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    body = finalized.json()
    assert body["gross"]["extra_pay"] == "350.50"
    payroll = body["payroll"]
    assert payroll is not None
    # the flat amount flows straight into every FICA/State base and into the
    # annualized federal figure — no dedicated line in the payroll result.
    # $1,538 annualized = $79,976 less the $8,600 offset = $71,376, which crosses
    # into the 22% bracket: $5,800 + 13,476 x 0.22 = $8,764.72/yr = $168.55.
    assert payroll["gross"] == "1538.00"
    assert payroll["withholding"]["social_security"] == "95.36"
    assert payroll["withholding"]["medicare"] == "22.30"
    assert payroll["withholding"]["federal_income_tax"] == "168.55"
    assert payroll["withholding"]["wa_pfml_employee"] == "12.41"
    assert payroll["withholding"]["wa_cares_employee"] == "8.92"
    assert payroll["withholding"]["total"] == "307.54"
    assert payroll["net_pay"] == "1230.46"

    # and the annual reports see it as ordinary wages
    summary = client.get("/tax-years/2026/earnings-summary")
    assert summary.status_code == 200
    assert summary.json()[0]["extra_pay"] == "350.50"

    w2 = client.get("/tax-years/2026/w2")
    assert w2.status_code == 200
    assert w2.json()[0]["box1_wages"] == "1538.00"
    assert w2.json()[0]["box3_ss_wages"] == "1538.00"


def test_extra_pay_line_validation(client: TestClient) -> None:
    _create_employer(client)
    employee = _create_employee(client)
    employee_id = employee["employee_id"]

    def create(lines: list[dict[str, str]]) -> Any:
        return client.post(
            f"/payruns/employees/{employee_id}",
            json={
                "period_start": "2026-01-05",
                "period_end": "2026-01-11",
                "pay_date": "2026-01-16",
                "extra_pay_lines": lines,
            },
        )

    # blank note rejected
    assert create([{"note": "   ", "amount": "250.00"}]).status_code == 422
    # negative amount rejected
    assert create([{"note": "Clawback", "amount": "-250.00"}]).status_code == 422
    # amount required
    assert create([{"note": "Bonus"}]).status_code == 422


def test_extra_pay_amount_rejects_float() -> None:
    """A JSON number is a float, and `Money` refuses floats outright.

    Asserted at the model boundary rather than over HTTP: a `TypeError` raised
    inside a Pydantic validator is not turned into a 422 by FastAPI.
    """
    with pytest.raises(TypeError):
        ExtraPayLine(note="Bonus", amount=250.5)  # type: ignore[arg-type]
