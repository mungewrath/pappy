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
    es_period_bounds,
    es_period_of,
    estimate_due_date,
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


def test_es_period_of_and_bounds() -> None:
    # The 1040-ES payment periods are deliberately uneven: Q2 is only
    # April and May, Q3 absorbs June, Q4 runs four months to year end.
    assert es_period_of(date(2026, 1, 16)) == 1
    assert es_period_of(date(2026, 3, 31)) == 1
    assert es_period_of(date(2026, 4, 17)) == 2
    assert es_period_of(date(2026, 5, 31)) == 2
    assert es_period_of(date(2026, 6, 1)) == 3
    assert es_period_of(date(2026, 8, 31)) == 3
    assert es_period_of(date(2026, 9, 4)) == 4
    assert es_period_of(date(2026, 12, 31)) == 4

    assert es_period_bounds(2026, 2) == (date(2026, 4, 1), date(2026, 5, 31))
    assert es_period_bounds(2026, 3) == (date(2026, 6, 1), date(2026, 8, 31))
    assert es_period_bounds(2026, 4) == (date(2026, 9, 1), date(2026, 12, 31))


def test_quarter_of_stays_calendar() -> None:
    # Calendar quarters remain available for informational groupings.
    assert quarter_of(date(2026, 1, 16)) == 1
    assert quarter_of(date(2026, 4, 17)) == 2
    assert quarter_of(date(2026, 12, 31)) == 4


def test_june_and_september_runs_leave_quarters_two_and_three() -> None:
    # A June paycheck belongs to ES period 3 (paid Sep 15), a September
    # paycheck to period 4 — never to the Q2/Q3 calendar buckets.
    june = make_contribution(date(2026, 6, 19))
    september = make_contribution(date(2026, 9, 18))

    quarters = aggregate_quarterly([june, september], tax_year=2026)

    assert quarters[0].totals.pay_run_count == 0
    assert quarters[1].totals.pay_run_count == 0
    assert quarters[2].totals.pay_run_count == 1
    assert quarters[3].totals.pay_run_count == 1


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
