"""Schedule H (Form 1040) worksheet builder (design-doc.md §6.4).

Maps the year's folded totals onto the form's lines. The line-numbered
fields follow Schedule H Part I:

- A/B — cash wages subject to Social Security (the wage-base-capped slices
  actually taxed at finalization) and the combined 12.4% tax
- C/D — Medicare wages (all cash wages; uncapped) and the combined 2.9% tax
- F/G — wages above the Additional Medicare threshold and the 0.9% withheld
  on them
- E/H/I/J — FICA subtotal, withheld federal income tax, total household
  employment taxes
- L/M — FUTA accrued on the first $7,000 of wages per employee, and the
  grand total

`contributing_runs` is the audit worksheet: every finalized run that fed a
line, so an IRS notice months later can be answered from the archive
without recomputing anything.
"""

from __future__ import annotations

from pappy.calc.tax_year import RunContribution, aggregate_year, sort_chronologically
from pappy.models.reports import ContributingRun, ScheduleHWorksheet
from pappy.money import Money


def build_schedule_h(
    contributions: list[RunContribution],
    *,
    tax_year: int,
    employer_name: str,
    employer_ein: str,
) -> ScheduleHWorksheet:
    """Fold the year's runs into Schedule H Part I line values."""
    year = aggregate_year(contributions)

    line_e = year.social_security + year.medicare
    line_h = line_e + year.additional_medicare
    line_j = line_h + year.federal_income_tax_withheld

    return ScheduleHWorksheet(
        tax_year=tax_year,
        employer_name=employer_name,
        employer_ein=employer_ein,
        line_a_ss_wages=_wage_slice(contributions, ss=True),
        line_b_ss_tax=year.social_security,
        line_c_medicare_wages=year.gross,
        line_d_medicare_tax=year.medicare,
        line_e_subtotal=line_e,
        line_f_addl_medicare_wages=_wage_slice(contributions, ss=False),
        line_g_addl_medicare_tax=year.additional_medicare,
        line_h_household_fica_taxes=line_h,
        line_i_fit_withheld=year.federal_income_tax_withheld,
        line_j_total_household_employment_taxes=line_j,
        line_l_futa_tax=year.futa,
        line_m_total=line_j + year.futa,
        contributing_runs=[
            ContributingRun(
                run_id=c.run_id,
                employee_id=c.employee_id,
                pay_date=c.pay_date,
                gross=c.gross,
                social_security=c.social_security,
                medicare=c.medicare,
                additional_medicare=c.additional_medicare,
                federal_income_tax_withheld=c.federal_income_tax_withheld,
                futa=c.futa,
            )
            for c in sort_chronologically(contributions)
        ],
    )


def _wage_slice(contributions: list[RunContribution], *, ss: bool) -> Money:
    """Line A (ss=True) or line F (ss=False): the summed taxable slice.

    These are covered-wage quantities stored full-precision on each run;
    quantizing once here is their first and only monetary rendering.
    """
    total = sum(
        (c.ss_wages if ss else c.additional_medicare_wages for c in contributions),
        start=0,
    )
    return Money(total)
