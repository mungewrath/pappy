"""PayRun CRUD + draft lifecycle business logic (design-doc.md §3.2, §6.1).

Withholding/net/employer-accrual computation is not implemented yet (see
`pappy.calc.gross` module docstring) — `finalize` here only locks the gross
figure and records a rate-table version, matching as much of the design as
Phase 1's calculation engine will support once it lands.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import PayRunStatus
from pappy.models.employee import DefaultScheduleLine
from pappy.models.payrun import HourLine, PayRun, PayRunCreate
from pappy.repo import employee_repo, payrun_repo
from pappy.repo.exceptions import InvalidStateError

# Placeholder until the Phase 1 rate-table store exists (design-doc.md §5.2,
# §9 Phase 1). Every finalized run records *some* version so the field is
# never silently null once finalized, and callers have a stable value to
# assert against in tests.
UNVERSIONED_RATE_TABLE = 0


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
    Lambda itself (EventBridge-triggered) is out of scope for this pass; this
    is the pure logic it would call, exposed here so `create_draft` also
    benefits from it when the caller omits hour lines.
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


def finalize_run(
    table: Table, employer_id: str, run_id: str, *, rate_table_version: int | None = None
) -> PayRun:
    run = payrun_repo.find(table, employer_id, run_id)
    if run.status != PayRunStatus.DRAFT:
        raise InvalidStateError(f"Cannot finalize a {run.status.value} PayRun")
    version = rate_table_version if rate_table_version is not None else UNVERSIONED_RATE_TABLE
    return payrun_repo.finalize(table, run, rate_table_version=version)
