"""Historical entry + bulk finalization (Phase 6): backfill creates weekly
drafts without touching existing runs, and finalization only produces
correct wage-base caps when runs lock oldest-first — which is why the
service enforces that order and why `finalize_pending_runs` stops at the
first failure.
"""

from datetime import date
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import Address, PayRunStatus
from pappy.models.employee import DefaultScheduleLine, Employee, EmployeeCreate
from pappy.models.employer import Employer, EmployerCreate
from pappy.models.payrun import PayRunCreate
from pappy.models.ratetable import RateTable
from pappy.models.reports import BackfillCreate, BackfillMode
from pappy.models.w4 import W4Election
from pappy.repo import employee_repo, employer_repo, payrun_repo, w4_repo, ytd_repo
from pappy.repo.exceptions import InvalidStateError
from pappy.services import payrun_service


def _employee(employer_id: str) -> Employee:
    return Employee.new(
        employer_id=employer_id,
        employee_id="nanny-1",
        data=EmployeeCreate(
            full_name="Nanny Smith",
            address=Address(line1="2 Elm St", city="Seattle", state="WA", zip_code="98102"),
            hire_date=date(2025, 1, 1),
            hourly_rate=Decimal("25.00"),
            default_schedule=[
                DefaultScheduleLine(weekday=weekday, hours=Decimal(9)) for weekday in range(5)
            ],
        ),
    )


@pytest.fixture
def household(dynamodb_table: Table) -> tuple[str, str]:
    employer = employer_repo.put(
        dynamodb_table,
        Employer.new(
            employer_id="emp-1",
            data=EmployerCreate(
                legal_name="Jane Doe",
                ein="12-3456789",
                address=Address(line1="1 Main St", city="Seattle", state="WA", zip_code="98101"),
            ),
        ),
    )
    employee = employee_repo.put(dynamodb_table, _employee(employer.employer_id))
    return employer.employer_id, employee.employee_id


def _week(spec: BackfillCreate) -> BackfillCreate:
    return spec


def test_backfill_creates_weekly_drafts_seeded_from_schedule(
    dynamodb_table: Table, seeded_rates: RateTable, household: tuple[str, str]
) -> None:
    employer_id, employee_id = household

    result = payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(period_start=date(2026, 1, 5), period_end=date(2026, 2, 1)),
    )

    assert [run.pay_date for run in result.created] == [
        date(2026, 1, 16),
        date(2026, 1, 23),
        date(2026, 1, 30),
        date(2026, 2, 6),
    ]
    assert result.skipped == []
    first = result.created[0]
    assert (first.period_start, first.period_end) == (date(2026, 1, 5), date(2026, 1, 11))
    assert str(first.gross.gross) == "1187.50"  # 45h at $25 with the OT premium
    assert all(run.status == PayRunStatus.DRAFT for run in result.created)


def test_backfill_flat_mode_spreads_hours_across_workdays(
    dynamodb_table: Table, seeded_rates: RateTable, household: tuple[str, str]
) -> None:
    employer_id, employee_id = household

    result = payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(
            period_start=date(2026, 1, 5),
            period_end=date(2026, 1, 11),
            mode=BackfillMode.FLAT,
            weekly_hours=Decimal(20),
        ),
    )

    draft = result.created[0]
    assert len(draft.hour_lines) == 5
    assert all(str(line.hours) == "4" for line in draft.hour_lines)
    assert str(draft.gross.gross) == "500.00"  # no overtime below the threshold


def test_backfill_skips_weeks_overlapping_existing_runs(
    dynamodb_table: Table, seeded_rates: RateTable, household: tuple[str, str]
) -> None:
    employer_id, employee_id = household
    existing = payrun_service.create_draft(
        dynamodb_table,
        employer_id,
        employee_id,
        PayRunCreate(
            period_start=date(2026, 1, 12),
            period_end=date(2026, 1, 18),
            pay_date=date(2026, 1, 23),
        ),
    )

    result = payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(period_start=date(2026, 1, 5), period_end=date(2026, 2, 1)),
    )

    assert len(result.created) == 3
    assert [skip.period_start for skip in result.skipped] == [date(2026, 1, 12)]
    # the pre-existing run was not touched or re-finalized
    assert payrun_repo.find(dynamodb_table, employer_id, existing.run_id).run_id == existing.run_id


def test_finalize_pending_locks_chronologically_regardless_of_creation_order(
    dynamodb_table: Table, seeded_rates: RateTable, household: tuple[str, str]
) -> None:
    employer_id, employee_id = household
    w4_repo.put(dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1)))

    # the later week is created first — historical entry out of order
    payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(period_start=date(2026, 8, 3), period_end=date(2026, 8, 9)),
    )
    payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(period_start=date(2026, 1, 5), period_end=date(2026, 1, 11)),
    )

    result = payrun_service.finalize_pending_runs(dynamodb_table, employer_id)

    assert result.failed == []
    locked = [payrun_repo.find(dynamodb_table, employer_id, run_id) for run_id in result.finalized]
    assert len(locked) == 2
    # The January week locked first even though it was created second, so
    # both weeks' wage-base slices accumulated in true order.
    assert all(run.status == PayRunStatus.FINALIZED for run in locked)
    ytd = ytd_repo.get_or_none(dynamodb_table, employer_id, employee_id, 2026)
    assert ytd is not None
    assert ytd.futa_wages == Decimal("2375.00")


def test_out_of_order_finalization_is_refused(
    dynamodb_table: Table, seeded_rates: RateTable, household: tuple[str, str]
) -> None:
    employer_id, employee_id = household
    w4_repo.put(dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1)))

    january = payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(period_start=date(2026, 1, 5), period_end=date(2026, 1, 11)),
    ).created[0]
    august = payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        employee_id,
        BackfillCreate(period_start=date(2026, 8, 3), period_end=date(2026, 8, 9)),
    ).created[0]

    payrun_service.finalize_run(dynamodb_table, employer_id, august.run_id)
    with pytest.raises(InvalidStateError):
        payrun_service.finalize_run(dynamodb_table, employer_id, january.run_id)

    still_draft = payrun_repo.find(dynamodb_table, employer_id, january.run_id)
    assert still_draft.status == PayRunStatus.DRAFT


def test_finalize_pending_stops_at_first_failure(
    dynamodb_table: Table, seeded_rates: RateTable, household: tuple[str, str]
) -> None:
    """No W-4 on the earliest week: nothing finalizes, because continuing
    would compute later runs against an accumulator missing that week."""
    employer_id, _employee_id = household

    payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        _employee_id,
        BackfillCreate(period_start=date(2026, 1, 5), period_end=date(2026, 1, 11)),
    )
    payrun_service.create_backfill_drafts(
        dynamodb_table,
        employer_id,
        _employee_id,
        BackfillCreate(period_start=date(2026, 1, 12), period_end=date(2026, 1, 18)),
    )

    result = payrun_service.finalize_pending_runs(dynamodb_table, employer_id)

    assert result.finalized == []
    assert len(result.failed) == 1
    assert "W-4" in result.failed[0].detail
    runs = payrun_repo.list_for_employer(dynamodb_table, employer_id, year=2026)
    assert all(run.status == PayRunStatus.DRAFT for run in runs)
