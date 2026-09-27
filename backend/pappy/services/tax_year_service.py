"""Tax-year artifact business logic (design-doc.md §9 Phase 6).

Everything here reads *finalized* runs only and consumes their stored
computations ("compute once, store the result", §3 principle 3) — no rate
table or W-4 resolution happens at report time, so regenerating a 2027 W-2
in 2031 depends only on the ledger.

The one deliberate read of current configuration is the earnings summary's
wage-base section, which pairs the stored YTD accumulators (§4) with the
current rate table's caps for planning display.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pappy.calc.efw2 import Efw2WageRecord, build_efw2, split_full_name
from pappy.calc.payroll import EmployeeWithholding, EmployerAccruals
from pappy.calc.tax_year import (
    RunContribution,
    aggregate_quarterly,
    es_period_bounds,
    estimate_due_date,
    quarter_of,
)
from pappy.models.common import PayRunStatus
from pappy.models.employee import Employee
from pappy.models.payrun import PayRun
from pappy.models.ratetable import RateTable
from pappy.models.reports import (
    EarningsSummary,
    QuarterEstimate,
    QuarterGross,
    QuarterlyEstimates,
    ScheduleHWorksheet,
    W2Summary,
    WageBaseUsage,
)
from pappy.models.ytd import YtdAccumulator
from pappy.money import Money
from pappy.repo import employee_repo, employer_repo, payrun_repo, rate_table_repo, ytd_repo

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


def _sum_money(amounts: list[Money]) -> Money:
    """Year-total a line across runs; empty years stay at zero."""
    return Money.sum(amounts)


def _year_runs(table: Table, employer_id: str, tax_year: int) -> list[PayRun]:
    """Finalized, non-voided runs whose pay date falls in the tax year."""
    runs = payrun_repo.list_for_employer(table, employer_id, year=tax_year)
    return [
        run
        for run in runs
        if run.status == PayRunStatus.FINALIZED
        and run.payroll is not None
        and run.pay_date.year == tax_year
    ]


def _to_contribution(run: PayRun) -> RunContribution:
    """Reduce a finalized run to its year-artifact lines."""
    payroll = run.payroll
    assert payroll is not None  # guaranteed by _year_runs
    return RunContribution(
        run_id=run.run_id,
        employee_id=run.employee_id,
        pay_date=run.pay_date,
        gross=payroll.gross,
        federal_income_tax_withheld=payroll.withholding.federal_income_tax,
        ee_social_security=payroll.withholding.social_security,
        er_social_security=payroll.employer_accruals.social_security,
        ee_medicare=payroll.withholding.medicare,
        er_medicare=payroll.employer_accruals.medicare,
        additional_medicare=payroll.withholding.additional_medicare,
        futa=payroll.employer_accruals.futa,
        wa_pfml_employee=payroll.withholding.wa_pfml_employee,
        wa_cares_employee=payroll.withholding.wa_cares_employee,
        ss_wages=payroll.taxable.social_security,
        additional_medicare_wages=payroll.taxable.additional_medicare,
    )


def _contributions(table: Table, employer_id: str, tax_year: int) -> list[RunContribution]:
    return [_to_contribution(run) for run in _year_runs(table, employer_id, tax_year)]


def quarterly_estimates(table: Table, employer_id: str, tax_year: int) -> QuarterlyEstimates:
    """Quarterly 1040-ES figures, employer-wide — Schedule H covers all
    household employees together (design-doc.md §6.6)."""
    contributions = _contributions(table, employer_id, tax_year)
    quarters = aggregate_quarterly(contributions, tax_year=tax_year)

    estimates = [
        QuarterEstimate(
            quarter=q.quarter,
            period_start=es_period_bounds(tax_year, q.quarter)[0],
            period_end=es_period_bounds(tax_year, q.quarter)[1],
            due_date=estimate_due_date(tax_year, q.quarter),
            pay_run_count=q.totals.pay_run_count,
            gross=q.totals.gross,
            federal_income_tax_withheld=q.totals.federal_income_tax_withheld,
            social_security=q.totals.social_security,
            medicare=q.totals.medicare,
            additional_medicare=q.totals.additional_medicare,
            household_employment_taxes=q.totals.household_employment_taxes,
            futa=q.totals.futa,
            total=q.totals.total,
            ytd_total=q.ytd_total,
        )
        for q in quarters
    ]
    # Four rows always; the last row's running total *is* the year total.
    return QuarterlyEstimates(tax_year=tax_year, quarters=estimates, grand_total=estimates[-1].ytd_total)


def schedule_h_worksheet(table: Table, employer_id: str, tax_year: int) -> ScheduleHWorksheet:
    """Schedule H line values plus the contributing-run worksheet (§6.4)."""
    from pappy.calc.schedule_h import build_schedule_h

    employer = employer_repo.get(table, employer_id)
    contributions = _contributions(table, employer_id, tax_year)
    return build_schedule_h(
        contributions,
        tax_year=tax_year,
        employer_name=employer.legal_name,
        employer_ein=employer.ein,
    )


def w2_summary(table: Table, employer_id: str, employee_id: str, tax_year: int) -> W2Summary:
    """W-2 box values for one employee (design-doc.md §6.5)."""
    from pappy.calc.w2 import build_w2_summary

    employer = employer_repo.get(table, employer_id)
    employee = employee_repo.get(table, employer_id, employee_id)
    contributions = [
        c
        for c in _contributions(table, employer_id, tax_year)
        if c.employee_id == employee_id
    ]
    return build_w2_summary(
        contributions,
        tax_year=tax_year,
        employer_name=employer.legal_name,
        employer_ein=employer.ein,
        employee_id=employee_id,
        employee_name=employee.full_name,
    )


def w2_summaries(table: Table, employer_id: str, tax_year: int) -> list[W2Summary]:
    """W-2 box values for every employee with runs in the year."""
    from pappy.calc.w2 import build_w2_summary

    employer = employer_repo.get(table, employer_id)
    names = {e.employee_id: e.full_name for e in employee_repo.list_for_employer(table, employer_id)}
    by_employee: dict[str, list[RunContribution]] = {}
    for contribution in _contributions(table, employer_id, tax_year):
        by_employee.setdefault(contribution.employee_id, []).append(contribution)
    return [
        build_w2_summary(
            contributions,
            tax_year=tax_year,
            employer_name=employer.legal_name,
            employer_ein=employer.ein,
            employee_id=employee_id,
            employee_name=names.get(employee_id, employee_id),
        )
        for employee_id, contributions in sorted(by_employee.items())
    ]


def earnings_summaries(table: Table, employer_id: str, tax_year: int) -> list[EarningsSummary]:
    """One annual summary per employee (§5.4, §6.6): overtime-premium
    breakdown, every withholding line as a year total, quarterly gross
    progression, and wage-base consumption from the YTD accumulators."""
    employees = employee_repo.list_for_employer(table, employer_id)
    runs = _year_runs(table, employer_id, tax_year)
    rates = rate_table_repo.latest_for_year(table, tax_year)

    summaries = [
        _earnings_summary_for(
            employee,
            [r for r in runs if r.employee_id == employee.employee_id],
            table=table,
            employer_id=employer_id,
            tax_year=tax_year,
            rates=rates,
        )
        for employee in sorted(employees, key=lambda e: e.full_name)
    ]
    return summaries


def _earnings_summary_for(
    employee: Employee,
    runs: list[PayRun],
    *,
    table: Table,
    employer_id: str,
    tax_year: int,
    rates: RateTable | None,
) -> EarningsSummary:
    payrolls = [run.payroll for run in runs if run.payroll is not None]
    gross_results = [run.gross for run in runs]

    withholding = EmployeeWithholding(
        social_security=_sum_money([p.withholding.social_security for p in payrolls]),
        medicare=_sum_money([p.withholding.medicare for p in payrolls]),
        additional_medicare=_sum_money([p.withholding.additional_medicare for p in payrolls]),
        federal_income_tax=_sum_money([p.withholding.federal_income_tax for p in payrolls]),
        wa_pfml_employee=_sum_money([p.withholding.wa_pfml_employee for p in payrolls]),
        wa_cares_employee=_sum_money([p.withholding.wa_cares_employee for p in payrolls]),
    )
    accruals = EmployerAccruals(
        social_security=_sum_money([p.employer_accruals.social_security for p in payrolls]),
        medicare=_sum_money([p.employer_accruals.medicare for p in payrolls]),
        futa=_sum_money([p.employer_accruals.futa for p in payrolls]),
        wa_ui=_sum_money([p.employer_accruals.wa_ui for p in payrolls]),
        wa_pfml_employer=_sum_money([p.employer_accruals.wa_pfml_employer for p in payrolls]),
    )

    quarter_totals = {q: Decimal(0) for q in range(1, 5)}
    for run in runs:
        quarter_totals[quarter_of(run.pay_date)] += run.gross.gross.amount

    quarterly_gross: list[QuarterGross] = []
    running = Decimal(0)
    for quarter in range(1, 5):
        running += quarter_totals[quarter]
        quarterly_gross.append(
            QuarterGross(
                quarter=quarter,
                gross=Money(quarter_totals[quarter]),
                ytd_gross=Money(running),
            )
        )

    ytd = ytd_repo.get_or_none(table, employer_id, employee.employee_id, tax_year)
    return EarningsSummary(
        tax_year=tax_year,
        employee_id=employee.employee_id,
        employee_name=employee.full_name,
        hourly_rate=employee.hourly_rate,
        finalized_run_count=len(runs),
        hours_regular=sum((g.regular_hours for g in gross_results), Decimal(0)),
        hours_overtime=sum((g.overtime_hours for g in gross_results), Decimal(0)),
        hours_other_paid=sum((g.other_paid_hours for g in gross_results), Decimal(0)),
        hours_unpaid=sum((g.unpaid_hours for g in gross_results), Decimal(0)),
        straight_time_pay=_sum_money([g.straight_time_pay for g in gross_results]),
        overtime_premium_pay=_sum_money([g.overtime_premium_pay for g in gross_results]),
        extra_pay=_sum_money([g.extra_pay for g in gross_results]),
        gross=_sum_money([p.gross for p in payrolls]),
        withholding=withholding,
        net_pay=_sum_money([p.net_pay for p in payrolls]),
        employer_accruals=accruals,
        quarterly_gross=quarterly_gross,
        wage_bases=_wage_bases(rates, ytd),
    )


def _wage_bases(rates: RateTable | None, ytd: YtdAccumulator | None) -> list[WageBaseUsage]:
    """Pair this year's covered-wage totals with the current caps."""
    if rates is None:
        return []
    used = ytd if ytd is not None else YtdAccumulator(
        employer_id="", employee_id="", tax_year=rates.tax_year
    )
    entries = [
        ("social_security", "Social Security wages", used.social_security_wages, rates.social_security.wage_base),
        ("medicare", "Medicare wages (no cap)", used.medicare_wages, None),
        ("futa", "FUTA wages", used.futa_wages, rates.futa.wage_base),
        ("wa_ui", "WA UI wages", used.wa_ui_wages, rates.wa_ui.wage_base),
        ("wa_pfml", "WA PFML wages", used.wa_pfml_wages, rates.wa_pfml.wage_base),
    ]
    return [
        WageBaseUsage(
            name=name,
            label=label,
            wages_used=wages_used,
            wage_base=wage_base,
            remaining=None if wage_base is None else max(Decimal(0), wage_base - wages_used),
        )
        for name, label, wages_used, wage_base in entries
    ]


def efw2_file(
    table: Table,
    employer_id: str,
    tax_year: int,
    employee_ssns: dict[str, str] | None = None,
) -> str:
    """Build the BSO upload file (§6.5).

    SSNs are supplied transiently per request and never persisted or
    logged (§7.3); an employee without one produces a blank-SSN RW record
    that previews fine but would be rejected at upload.
    """
    employer = employer_repo.get(table, employer_id)
    employees = {
        e.employee_id: e for e in employee_repo.list_for_employer(table, employer_id)
    }
    by_employee: dict[str, list[RunContribution]] = {}
    for contribution in _contributions(table, employer_id, tax_year):
        by_employee.setdefault(contribution.employee_id, []).append(contribution)

    ssns = employee_ssns or {}
    wage_records: list[Efw2WageRecord] = []
    for employee_id, contributions in sorted(by_employee.items()):
        employee = employees.get(employee_id)
        if employee is None:
            continue
        first, middle, last = split_full_name(employee.full_name)
        wage_records.append(
            Efw2WageRecord(
                first_name=first,
                middle_initial=middle,
                last_name=last,
                ssn=ssns.get(employee_id),
                wages=_sum_money([c.gross for c in contributions]),
                fit_withheld=_sum_money([c.federal_income_tax_withheld for c in contributions]),
                ss_wages=Money(sum((c.ss_wages for c in contributions), Decimal(0))),
                ss_tax_withheld=_sum_money([c.ee_social_security for c in contributions]),
                medicare_wages=_sum_money([c.gross for c in contributions]),
                medicare_tax_withheld=_sum_money(
                    [c.ee_medicare + c.additional_medicare for c in contributions]
                ),
            )
        )

    address = employer.address
    return build_efw2(
        tax_year=tax_year,
        ein=employer.ein,
        employer_name=employer.legal_name,
        city=address.city,
        state=address.state,
        zip_code=address.zip_code,
        wage_records=wage_records,
    )
