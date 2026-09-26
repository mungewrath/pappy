"""PayRun CRUD + draft lifecycle business logic (design-doc.md ss3.2, ss6.1).

The core loop (ss9 Phase 2): a DRAFT run is seeded from the employee's
default schedule, edited until it looks right, then finalized -- which
resolves the W-4 in effect on the pay date (ss5.3), loads the current rate
table for the tax year (ss5.2), computes withholding/net/employer accruals
from the year-to-date wage-base context, and stores everything atomically
together with the advanced YTD accumulator (ss4). After that the run is
immutable.

Phase 6 adds historical entry (backfill): whole date ranges of weekly
drafts created in one call, plus a bulk finalization that locks pending
drafts oldest-first -- the only order that keeps the wage-base accumulators
correct when history arrives after the fact (ss4).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.calc.fit import MissingW4Error, resolve_w4
from pappy.calc.payroll import YtdContext, compute_payroll
from pappy.models.common import PayRunStatus
from pappy.models.employee import DefaultScheduleLine, Employee
from pappy.models.payrun import ExtraPayLine, HourLine, PayRun, PayRunCreate
from pappy.models.reports import (
    BackfillCreate,
    BackfillMode,
    BackfillResult,
    FinalizeFailure,
    FinalizePendingResult,
    SkippedWeek,
)
from pappy.repo import employee_repo, employer_repo, payrun_repo, w4_repo, ytd_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError
from pappy.repo.rate_table_repo import latest_for_year as rate_table_latest_for_year


def list_runs(
    table: Table, employer_id: str, *, year: int | None = None
) -> list[PayRun]:
    return payrun_repo.list_for_employer(table, employer_id, year=year)


def get_draft_or_run(table: Table, employer_id: str, run_id: str) -> PayRun:
    return payrun_repo.find(table, employer_id, run_id)


def create_draft(
    table: Table, employer_id: str, employee_id: str, data: PayRunCreate
) -> PayRun:
    """Open a new draft. Auto-populates hours from the default schedule
    when ``data.hour_lines`` is empty (design-doc.md ss6.1)."""
    employee = employee_repo.get(table, employer_id, employee_id)
    hour_lines = data.hour_lines
    if not hour_lines:
        hour_lines = _auto_populate_hours(
            data.period_start, data.period_end, employee.default_schedule
        )
    draft = PayRun.new_draft(
        employer_id=employer_id,
        employee_id=employee_id,
        run_id=uuid.uuid4().hex,
        data=PayRunCreate(
            period_start=data.period_start,
            period_end=data.period_end,
            pay_date=data.pay_date,
            hour_lines=hour_lines,
        ),
        hourly_rate=employee.hourly_rate,
        overtime_policy=employee.overtime_policy,
    )
    return payrun_repo.create(table, draft)


def _auto_populate_hours(
    period_start: date,
    period_end: date,
    schedule: list[DefaultScheduleLine],
) -> list[HourLine]:
    """Seed hour lines from the employee's default weekly schedule
    (design-doc.md ss6.1)."""
    lines: list[HourLine] = []
    current = period_start
    while current <= period_end:
        for entry in schedule:
            if current.weekday() == entry.weekday:
                lines.append(HourLine(work_date=current, hours=entry.hours))
        current += timedelta(days=1)
    return lines


def update_draft(
    table: Table,
    employer_id: str,
    run_id: str,
    hour_lines: list[HourLine],
    extra_pay_lines: list[ExtraPayLine],
) -> PayRun:
    run = payrun_repo.find(table, employer_id, run_id)
    if run.status != PayRunStatus.DRAFT:
        raise InvalidStateError(f"Cannot edit a {run.status.value} PayRun")
    employee = employee_repo.get(table, employer_id, run.employee_id)
    updated = run.with_recomputed_pay(
        hour_lines,
        extra_pay_lines,
        hourly_rate=employee.hourly_rate,
        overtime_policy=employee.overtime_policy,
    )
    return payrun_repo.save_draft(table, updated)


def finalize_run(
    table: Table, employer_id: str, run_id: str
) -> PayRun:
    """Compute and lock a draft run (design-doc.md ss3.2, ss4, ss5.4).

    Returns the finalized run.

    Raises before any write:

    - ``NotFoundError`` when no rate table has been seeded for the pay
      date's tax year;
    - ``MissingW4Error`` when no W-4 election is in effect on the pay date;
    - ``InvalidStateError`` when an already-finalized run for the same
      employee pays *earlier* in the year.
    """
    run = payrun_repo.find(table, employer_id, run_id)
    if run.status != PayRunStatus.DRAFT:
        raise InvalidStateError(f"Cannot finalize a {run.status.value} PayRun")

    _enforce_chronological_order(table, employer_id, run)

    employer = employer_repo.get(table, employer_id)
    tax_year = run.pay_date.year

    elections = w4_repo.list_for_employee(table, employer_id, run.employee_id)
    w4 = resolve_w4(elections, pay_date=run.pay_date)

    rates = rate_table_latest_for_year(table, tax_year)
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


def _enforce_chronological_order(
    table: Table, employer_id: str, run: PayRun
) -> None:
    """Refuse to finalize a run earlier than an already-finalized one for
    the same employee and tax year (ss4: caps are running totals)."""
    year_runs = payrun_repo.list_for_employer(
        table, employer_id, year=run.pay_date.year
    )
    for other in year_runs:
        if (
            other.employee_id == run.employee_id
            and other.status == PayRunStatus.FINALIZED
            and run.pay_date < other.pay_date
        ):
            raise InvalidStateError(
                f"Cannot finalize: {run.pay_date.isoformat()} precedes the already-"
                f"finalized {other.pay_date.isoformat()}. Historical runs must be "
                "finalized oldest-first so wage-base caps and quarterly figures stay "
                "correct."
            )


def create_backfill_drafts(
    table: Table, employer_id: str, employee_id: str, spec: BackfillCreate
) -> BackfillResult:
    """Create weekly DRAFT runs across a historical date range (Phase 6 historical
    entry).

    One draft per week from ``period_start``; weeks overlapping an existing
    run are skipped (never overwritten), as are weeks with no hours. Hours
    seed from the default schedule (``SCHEDULE``) or spread a flat weekly
    total evenly over the schedule's workdays (``FLAT``). Drafts only -- the
    caller reviews them and locks them with ``finalize_pending_runs``.
    """
    employee = employee_repo.get(table, employer_id, employee_id)
    existing = [
        run
        for run in payrun_repo.list_for_employer(table, employer_id)
        if run.employee_id == employee_id
    ]

    created: list[PayRun] = []
    skipped: list[SkippedWeek] = []
    for period_start, period_end in _weekly_periods(spec.period_start, spec.period_end):
        overlap = next(
            (
                run
                for run in existing
                if run.period_start <= period_end and period_start <= run.period_end
            ),
            None,
        )
        if overlap is not None:
            skipped.append(
                SkippedWeek(
                    period_start=period_start,
                    period_end=period_end,
                    reason=f"overlaps an existing run paid {overlap.pay_date.isoformat()}",
                )
            )
            continue

        hour_lines = _backfill_hours(employee, spec.mode, spec.weekly_hours, period_start, period_end)
        if not hour_lines:
            skipped.append(
                SkippedWeek(
                    period_start=period_start,
                    period_end=period_end,
                    reason="no scheduled hours that week",
                )
            )
            continue

        draft = PayRun.new_draft(
            employer_id=employer_id,
            employee_id=employee_id,
            run_id=uuid.uuid4().hex,
            data=PayRunCreate(
                period_start=period_start,
                period_end=period_end,
                pay_date=_next_weekday_after(period_end, spec.pay_weekday),
                hour_lines=hour_lines,
            ),
            hourly_rate=employee.hourly_rate,
            overtime_policy=employee.overtime_policy,
        )
        created.append(payrun_repo.create(table, draft))

    return BackfillResult(created=created, skipped=skipped)


def _weekly_periods(period_start: date, period_end: date) -> list[tuple[date, date]]:
    """Monday-starting weekly slices of [period_start, period_end]."""
    periods: list[tuple[date, date]] = []
    current_start = period_start
    while current_start <= period_end:
        current_end = min(current_start + timedelta(days=6), period_end)
        periods.append((current_start, current_end))
        current_start = current_end + timedelta(days=1)
    return periods


def _next_weekday_after(after: date, weekday: int) -> date:
    candidate = after + timedelta(days=1)
    while candidate.weekday() != weekday:
        candidate += timedelta(days=1)
    return candidate


def _backfill_hours(
    employee: Employee,
    mode: BackfillMode,
    weekly_hours: Decimal | None,
    period_start: date,
    period_end: date,
) -> list[HourLine]:
    """Hour lines for one backfilled week.

    SCHEDULE mode reuses the ss6.1 auto-population; FLAT mode spreads the
    weekly total evenly across the schedule's workdays so a 45-hour week
    still crosses the 40-hour overtime threshold naturally.
    """
    if mode == BackfillMode.SCHEDULE or weekly_hours is None:
        return _auto_populate_hours(period_start, period_end, employee.default_schedule)

    scheduled_weekdays = sorted({line.weekday for line in employee.default_schedule}) or [
        weekday for weekday in range(5)
    ]
    days = [d for d in _each_day(period_start, period_end) if d.weekday() in scheduled_weekdays]
    if not days:
        return []
    hours_per_day = weekly_hours / Decimal(len(days))
    return [HourLine(work_date=day, hours=hours_per_day) for day in days]


def _each_day(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def finalize_pending_runs(
    table: Table,
    employer_id: str,
    *,
    tax_year: int | None = None,
    employee_id: str | None = None,
) -> FinalizePendingResult:
    """Finalize pending drafts oldest-pay-date-first (Phase 6 historical
    entry).

    Chronological order keeps the YTD accumulators correct regardless of
    when the drafts were created. Processing **stops at the first failure**
    -- continuing past a failed run would finalize later runs against an
    accumulator missing that run's wages, understating wage-base caps.
    Remaining drafts stay pending and appear in the UI.
    """
    runs = payrun_repo.list_for_employer(table, employer_id, year=tax_year)
    drafts = [
        run
        for run in runs
        if run.status == PayRunStatus.DRAFT
        and (employee_id is None or run.employee_id == employee_id)
    ]
    drafts.sort(key=lambda r: (r.pay_date, r.run_id))

    finalized_ids: list[str] = []
    failures: list[FinalizeFailure] = []
    for draft in drafts:
        try:
            locked = finalize_run(table, employer_id, draft.run_id)
        except (InvalidStateError, NotFoundError, MissingW4Error) as exc:
            failures.append(
                FinalizeFailure(run_id=draft.run_id, pay_date=draft.pay_date, detail=str(exc))
            )
            break
        finalized_ids.append(locked.run_id)
    return FinalizePendingResult(finalized=finalized_ids, failed=failures)
