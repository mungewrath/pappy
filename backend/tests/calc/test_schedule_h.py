"""Schedule H worksheet mapping (design-doc.md §6.4).

Line goldens for two $1,187.50 runs in 2026 (see test_tax_year.py): the
combined halves give B = 12.4% of A and D = 2.9% of C, FUTA accrues per
run at the effective rate.
"""

from datetime import date
from decimal import Decimal

from pappy.calc.schedule_h import build_schedule_h
from pappy.calc.tax_year import RunContribution
from pappy.money import Money


def _contribution(pay_date: date) -> RunContribution:
    return RunContribution(
        run_id=f"run-{pay_date.isoformat()}",
        employee_id="nanny-1",
        pay_date=pay_date,
        gross=Money("1187.50"),
        federal_income_tax_withheld=Money("100.58"),
        ee_social_security=Money("73.63"),
        er_social_security=Money("73.63"),
        ee_medicare=Money("17.22"),
        er_medicare=Money("17.22"),
        futa=Money("7.13"),
        ss_wages=Decimal("1187.50"),
    )


def test_schedule_h_lines() -> None:
    worksheet = build_schedule_h(
        [_contribution(date(2026, 1, 16)), _contribution(date(2026, 4, 17))],
        tax_year=2026,
        employer_name="Jane Doe",
        employer_ein="12-3456789",
    )

    assert str(worksheet.line_a_ss_wages) == "2375.00"  # capped slices, both runs
    assert str(worksheet.line_b_ss_tax) == "294.52"
    assert str(worksheet.line_c_medicare_wages) == "2375.00"
    assert str(worksheet.line_d_medicare_tax) == "68.88"
    assert str(worksheet.line_e_subtotal) == "363.40"
    assert str(worksheet.line_f_addl_medicare_wages) == "0.00"
    assert str(worksheet.line_g_addl_medicare_tax) == "0.00"
    assert str(worksheet.line_h_household_fica_taxes) == "363.40"
    assert str(worksheet.line_i_fit_withheld) == "201.16"
    assert str(worksheet.line_j_total_household_employment_taxes) == "564.56"
    assert str(worksheet.line_l_futa_tax) == "14.26"
    assert str(worksheet.line_m_total) == "578.82"


def test_contributing_runs_are_the_audit_worksheet() -> None:
    dates = [date(2026, 4, 17), date(2026, 1, 16)]  # deliberately out of order
    worksheet = build_schedule_h(
        [_contribution(d) for d in dates],
        tax_year=2026,
        employer_name="Jane Doe",
        employer_ein="12-3456789",
    )
    pay_dates = [row.pay_date for row in worksheet.contributing_runs]
    assert pay_dates == sorted(dates)
    assert all(str(row.social_security) == "147.26" for row in worksheet.contributing_runs)


def test_empty_year_produces_zero_lines() -> None:
    worksheet = build_schedule_h(
        [], tax_year=2026, employer_name="Jane Doe", employer_ein="12-3456789"
    )
    assert str(worksheet.line_m_total) == "0.00"
    assert worksheet.contributing_runs == []
