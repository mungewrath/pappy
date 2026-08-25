"""Tax-year artifact endpoints end to end (Phase 6, design-doc.md §9).

Seeds a household with two finalized runs in different quarters of 2026
(the deterministic $1,187.50 week from the other suites) and checks the
1040-ES, Schedule H, W-2, earnings-summary, and EFW2 responses against
hand-derived goldens.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient


def _seed_household(client: TestClient) -> str:
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
            "hire_date": "2025-01-01",
            "hourly_rate": "25.00",
            "default_schedule": [
                {"weekday": weekday, "hours": "9"} for weekday in range(5)
            ],
        },
    )
    assert employee.status_code == 201, employee.text
    employee_id: str = employee.json()["employee_id"]

    w4 = client.post(
        f"/employees/{employee_id}/w4",
        json={"effective_date": "2026-01-01", "filing_status": "SINGLE_OR_MFS"},
    )
    assert w4.status_code == 201, w4.text
    return employee_id


def _finalize_week(client: TestClient, employee_id: str, period_start: str, pay_date: str) -> dict[str, Any]:
    from datetime import date, timedelta

    period_end = (date.fromisoformat(period_start) + timedelta(days=6)).isoformat()
    draft = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": period_start,
            "period_end": period_end,
            "pay_date": pay_date,
        },
    )
    assert draft.status_code == 201, draft.text
    run_id = draft.json()["run_id"]
    finalized = client.post(f"/payruns/{run_id}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    result: dict[str, Any] = finalized.json()
    return result


def _two_quarters_of_history(client: TestClient) -> str:
    employee_id = _seed_household(client)
    _finalize_week(client, employee_id, "2026-01-05", "2026-01-16")
    _finalize_week(client, employee_id, "2026-04-06", "2026-04-17")
    return employee_id


def test_quarterly_estimates(client: TestClient, seeded_rates: object) -> None:
    _two_quarters_of_history(client)

    response = client.get("/tax-years/2026/1040-es")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tax_year"] == 2026

    q1, q2, _q3, q4 = body["quarters"]
    assert str(q1["gross"]) == "1187.50"
    assert str(q1["federal_income_tax_withheld"]) == "100.58"
    assert str(q1["social_security"]) == "147.26"  # both halves
    assert str(q1["medicare"]) == "34.44"
    assert str(q1["household_employment_taxes"]) == "282.28"
    assert str(q1["futa"]) == "7.13"
    assert str(q1["total"]) == "289.41"
    assert q1["due_date"] == "2026-04-15"
    assert str(q1["ytd_total"]) == "289.41"

    # second quarter: same taxes but FUTA still accruing below the $7,000 base
    assert str(q2["total"]) == "289.41"
    assert str(q2["ytd_total"]) == "578.82"
    assert q4["due_date"] == "2027-01-15"
    # ES payment periods, not calendar quarters: Q2 ends May 31.
    assert q1["period_start"] == "2026-01-01"
    assert q1["period_end"] == "2026-03-31"
    assert q2["period_start"] == "2026-04-01"
    assert q2["period_end"] == "2026-05-31"
    assert _q3["period_start"] == "2026-06-01"
    assert _q3["period_end"] == "2026-08-31"
    assert q4["period_start"] == "2026-09-01"
    assert q4["period_end"] == "2026-12-31"

    assert str(body["grand_total"]) == "578.82"


def test_quarterly_estimates_for_a_quiet_year(client: TestClient) -> None:
    _seed_household(client)
    response = client.get("/tax-years/2031/1040-es")
    assert response.status_code == 200
    body = response.json()
    assert len(body["quarters"]) == 4
    assert all(str(q["total"]) == "0.00" for q in body["quarters"])
    assert str(body["grand_total"]) == "0.00"


def test_schedule_h_worksheet(client: TestClient, seeded_rates: object) -> None:
    _two_quarters_of_history(client)

    response = client.get("/tax-years/2026/schedule-h")
    assert response.status_code == 200, response.text
    h = response.json()
    assert h["employer_name"] == "Jane Doe"
    assert h["employer_ein"] == "12-3456789"
    assert str(h["line_a_ss_wages"]) == "2375.00"
    assert str(h["line_b_ss_tax"]) == "294.52"
    assert str(h["line_c_medicare_wages"]) == "2375.00"
    assert str(h["line_d_medicare_tax"]) == "68.88"
    assert str(h["line_j_total_household_employment_taxes"]) == "564.56"
    assert str(h["line_l_futa_tax"]) == "14.26"
    assert str(h["line_m_total"]) == "578.82"
    assert [row["pay_date"] for row in h["contributing_runs"]] == [
        "2026-01-16",
        "2026-04-17",
    ]


def test_w2_summary(client: TestClient, seeded_rates: object) -> None:
    _two_quarters_of_history(client)

    response = client.get("/tax-years/2026/w2")
    assert response.status_code == 200, response.text
    summaries = response.json()
    assert len(summaries) == 1
    w2 = summaries[0]
    assert w2["employee_name"] == "Nanny Smith"
    assert str(w2["box1_wages"]) == "2375.00"
    assert str(w2["box2_fit_withheld"]) == "201.16"
    assert str(w2["box3_ss_wages"]) == "2375.00"
    assert str(w2["box4_ss_tax_withheld"]) == "147.26"
    assert str(w2["box6_medicare_tax_withheld"]) == "34.44"
    box14 = {item["label"]: item["amount"] for item in w2["box14_items"]}
    assert str(box14["WA PFML employee contribution"]) == "19.18"
    assert str(box14["WA Cares Fund employee contribution"]) == "13.78"


def test_earnings_summary(client: TestClient, seeded_rates: object) -> None:
    employee_id = _two_quarters_of_history(client)

    response = client.get("/tax-years/2026/earnings-summary")
    assert response.status_code == 200, response.text
    summaries = response.json()
    assert len(summaries) == 1
    summary = summaries[0]
    assert summary["employee_id"] == employee_id
    assert summary["finalized_run_count"] == 2
    assert str(summary["hours_regular"]) == "90"
    assert str(summary["hours_overtime"]) == "10"
    assert str(summary["straight_time_pay"]) == "2250.00"
    assert str(summary["overtime_premium_pay"]) == "125.00"
    assert str(summary["gross"]) == "2375.00"
    assert str(summary["net_pay"]) == "1959.18"  # gross less 2 × $207.91 withheld

    quarterly_gross = {row["quarter"]: row for row in summary["quarterly_gross"]}
    assert str(quarterly_gross[1]["gross"]) == "1187.50"
    assert str(quarterly_gross[2]["ytd_gross"]) == "2375.00"

    wage_bases = {base["name"]: base for base in summary["wage_bases"]}
    assert str(wage_bases["social_security"]["wages_used"]) == "2375.00"
    assert str(wage_bases["social_security"]["remaining"]) == "182125.00"
    assert wage_bases["medicare"]["wage_base"] is None  # uncapped


def test_efw2_download_and_empty_year_rejected(
    client: TestClient, seeded_rates: object
) -> None:
    employee_id = _two_quarters_of_history(client)

    response = client.post(
        "/tax-years/2026/efw2",
        json={"employee_ssns": {employee_id: "123-45-6789"}},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    lines = response.text.rstrip("\r\n").split("\r\n")
    assert len(lines) == 2
    assert lines[0].startswith("RE") and len(lines[0]) == 512
    assert lines[1].startswith("RW")
    assert "NANNY" in lines[1]
    assert lines[1][15:24] == "123456789"  # dashes stripped

    empty_year = client.post("/tax-years/2031/efw2", json={"employee_ssns": {}})
    assert empty_year.status_code == 400
