"""PayRun CRUD + draft lifecycle business logic (design-doc.md §3.2, §6.1).

The core loop (§9 Phase 2): a DRAFT run is seeded from the employee's
default schedule, edited until it looks right, then finalized — which
resolves the W-4 in effect on the pay date (§5.3), loads the current rate
table for the tax year (§5.2), computes withholding/net/employer accruals
from the year-to-date wage-base context, and stores everything atomically
together with the advanced YTD accumulator (§4). After that the run is
immutable.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.calc.fit import resolve_w4
from pappy.calc.payroll import YtdContext, compute_payroll
from pappy.models.common import PayRunStatus
from pappy.models.employee import DefaultScheduleLine
from pappy.models.payrun import HourLine, PayRun, PayRunCreate
from pappy.repo import employee_repo, employer_repo, payrun_repo, rate_table_repo, w4_repo, ytd_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError


def create_draft(table: Table, employer_id: str, employee_id: str, data: PayRunCreate) -> PayRun:
    employee = employee_repo.get(table, employer_id, employee_id)

    hour_lines = data.hour_lines
    if not hour_lines and employee.default_schedule:
        hour_lines = _auto_populate_hours(
            data.period_start, data.period_end, employee.default_schedule
        )
        data = data.model_copy(update={"hour_lines": hour_lines})

    run = PayRun.new_draft(
        employer_id=employer_id,
        employee_id=employee_id,
        run_id=uuid.uuid4().hex,
        data=data,
        hourly_rate=employee.hourly_rate,
        overtime_policy=employee.overtime_policy,
    )
    return payrun_repo.create(table, run)


def _auto_populate_hours(
    period_start: date, period_end: date, schedule: list[DefaultScheduleLine]
) -> list[HourLine]:
    """Seed hour lines for every day in the period matching a scheduled weekday.

    Implements design-doc.md §6.1: "Each Friday morning, the scheduler
    Lambda creates a DRAFT run pre-filled from that schedule." The scheduler
    Lambda itself (EventBridge-triggered) arrives with Phase 4; this is the
    pure logic it will call, and it already serves interactive draft creation.
    """
    by_weekday = {line.weekday: line.hours for line in schedule}
    lines: list[HourLine] = []
    current = period_start
    while current <= period_end:
        hours = by_weekday.get(current.weekday())
        if hours is not None and hours > 0:
            lines.append(HourLine(work_date=current, hours=hours))
        current += timedelta(days=1)
    return lines


def get_draft_or_run(table: Table, employer_id: str, run_id: str) -> PayRun:
    return payrun_repo.find(table, employer_id, run_id)


def list_runs(table: Table, employer_id: str, *, year: int | None = None) -> list[PayRun]:
    return payrun_repo.list_for_employer(table, employer_id, year=year)


def update_hours(table: Table, employer_id: str, run_id: str, hour_lines: list[HourLine]) -> PayRun:
    run = payrun_repo.find(table, employer_id, run_id)
    if run.status != PayRunStatus.DRAFT:
        raise InvalidStateError(f"Cannot edit hours on a {run.status.value} PayRun")
    employee = employee_repo.get(table, employer_id, run.employee_id)
    updated = run.with_recomputed_hours(
        hour_lines, hourly_rate=employee.hourly_rate, overtime_policy=employee.overtime_policy
    )
    return payrun_repo.save_draft(table, updated)


def finalize_run(table: Table, employer_id: str, run_id: str) -> PayRun:
    """Compute and lock a draft run (§3.2, §4).

    Raises before any write:

    - `NotFoundError` when no rate table has been seeded for the pay date's
      tax year — rates are data (§5.2), and finalizing without them would
      silently mis-withhold;
    - `MissingW4Error` when no W-4 election is in effect on the pay date —
      a missing election blocks finalization rather than silently defaulting
      (§5.3).

    The rate-table version resolved here is recorded on the run; callers do
    not choose it.
    """
    run = payrun_repo.find(table, employer_id, run_id)
    if run.status != PayRunStatus.DRAFT:
        raise InvalidStateError(f"Cannot finalize a {run.status.value} PayRun")

    employer = employer_repo.get(table, employer_id)
    tax_year = run.pay_date.year

    elections = w4_repo.list_for_employee(table, employer_id, run.employee_id)
    w4 = resolve_w4(elections, pay_date=run.pay_date)

    rates = rate_table_repo.latest_for_year(table, tax_year)
    if rates is None:
        raise NotFoundError("RateTable", f"tax year {tax_year}")

    prior_ytd = ytd_repo.get_or_none(table, employer_id, run.employee_id, tax_year)
    ytd = (
        YtdContext(
            social_security_wages=prior_ytd.social_security_wages,
            medicare_wages=prior_ytd.medicare_wages,
            futa_wages=prior_ytd.futa_wages,
            wa_ui_wages=prior_ytd.wa_ui_wages,
            wa_pfml_wages=prior_ytd.wa_pfml_wages,
        )
        if prior_ytd is not None
        else None
    )

    payroll = compute_payroll(
        gross=run.gross.gross,
        w4=w4,
        rates=rates,
        ytd=ytd,
        wa_ui_experience_rate=(
            employer.wa_ui_experience_rate
            if employer.wa_ui_experience_rate is not None
            else Decimal(0)
        ),
    )

    finalized, _ = payrun_repo.finalize(
        table,
        run,
        rate_table_version=rates.version,
        payroll=payroll,
        tax_year=tax_year,
        prior_ytd=prior_ytd,
    )
    return finalized
