"""Tax-year aggregation over finalized runs (design-doc.md §5.3, §6.6).

Goldens use the deterministic 2026-table case: one $1,187.50 run pays
$100.58 FIT, $73.63+$73.63 Social Security, $17.22+$17.22 Medicare and
$7.13 FUTA (see tests/services/test_payrun_service.py for the derivation).
"""

from datetime import date
from decimal import Decimal

from pappy.calc.tax_year import (
    RunContribution,
    aggregate_quarterly,
    aggregate_year,
    estimate_due_date,
    quarter_bounds,
    quarter_of,
)
from pappy.money import Money


def make_contribution(
    pay_date: date, *, with_futa: bool = True, employee_id: str = "nanny-1"
) -> RunContribution:
    return RunContribution(
        run_id=f"run-{pay_date.isoformat()}",
        employee_id=employee_id,
        pay_date=pay_date,
        gross=Money("1187.50"),
        federal_income_tax_withheld=Money("100.58"),
        ee_social_security=Money("73.63"),
        er_social_security=Money("73.63"),
        ee_medicare=Money("17.22"),
        er_medicare=Money("17.22"),
        additional_medicare=Money("0.00"),
        futa=Money("7.13") if with_futa else Money("0.00"),
        ss_wages=Decimal("1187.50"),
        additional_medicare_wages=Decimal(0),
    )


def test_quarter_of_and_bounds() -> None:
    assert quarter_of(date(2026, 1, 16)) == 1
    assert quarter_of(date(2026, 4, 17)) == 2
    assert quarter_of(date(2026, 12, 31)) == 4
    assert quarter_bounds(2026, 2) == (date(2026, 4, 1), date(2026, 6, 30))


def test_due_dates() -> None:
    assert estimate_due_date(2026, 1) == date(2026, 4, 15)
    assert estimate_due_date(2026, 2) == date(2026, 6, 15)
    assert estimate_due_date(2026, 3) == date(2026, 9, 15)
    # Q4 estimates are paid with the return window — January of next year.
    assert estimate_due_date(2026, 4) == date(2027, 1, 15)


def test_quarterly_aggregation_with_running_ytd() -> None:
    q1_run = make_contribution(date(2026, 3, 20))
    q2_run = make_contribution(date(2026, 4, 17), with_futa=False)

    quarters = aggregate_quarterly([q2_run, q1_run], tax_year=2026)

    assert [q.quarter for q in quarters] == [1, 2, 3, 4]

    q1 = quarters[0].totals
    assert str(q1.gross) == "1187.50"
    assert str(q1.household_employment_taxes) == "282.28"
    assert str(q1.total) == "289.41"
    assert str(quarters[0].ytd_total) == "289.41"

    q2 = quarters[1].totals
    assert str(q2.total) == "282.28"  # no FUTA passed in for this fixture's second run
    assert str(quarters[1].ytd_total) == "571.69"

    # quiet quarters stay visible at zero, carrying the running total forward
    assert quarters[2].totals.pay_run_count == 0
    assert str(quarters[2].totals.total) == "0.00"
    assert str(quarters[3].ytd_total) == "571.69"


def test_runs_from_other_years_are_ignored() -> None:
    stray = make_contribution(date(2025, 12, 18))
    mine = make_contribution(date(2026, 1, 16))
    quarters = aggregate_quarterly([stray, mine], tax_year=2026)
    assert quarters[0].totals.pay_run_count == 1


def test_year_aggregation_sums_both_halves_and_wage_slices() -> None:
    contributions = [
        make_contribution(date(2026, 1, 16)),
        make_contribution(date(2026, 4, 17)),
    ]
    year = aggregate_year(contributions)
    assert str(year.social_security) == "294.52"
    assert str(year.medicare) == "68.88"
    assert str(year.federal_income_tax_withheld) == "201.16"
    assert str(year.futa) == "14.26"
    assert year.pay_run_count == 2
