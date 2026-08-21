from datetime import date
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import OvertimePolicy, PayRunStatus
from pappy.models.payrun import PayRun, PayRunCreate
from pappy.repo import payrun_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError


def _draft(employer_id: str = "emp-1", run_id: str = "run-1") -> PayRun:
    data = PayRunCreate(
        period_start=date(2026, 1, 5),
        period_end=date(2026, 1, 11),
        pay_date=date(2026, 1, 16),
    )
    return PayRun.new_draft(
        employer_id=employer_id,
        employee_id="nanny-1",
        run_id=run_id,
        data=data,
        hourly_rate=Decimal("25.00"),
        overtime_policy=OvertimePolicy.APPLIES,
    )


def test_create_and_get(dynamodb_table: Table) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)

    fetched = payrun_repo.get(dynamodb_table, "emp-1", date(2026, 1, 16), "run-1")
    assert fetched.status == PayRunStatus.DRAFT
    assert fetched.run_id == "run-1"


def test_find_by_run_id(dynamodb_table: Table) -> None:
    payrun_repo.create(dynamodb_table, _draft())
    found = payrun_repo.find(dynamodb_table, "emp-1", "run-1")
    assert found.run_id == "run-1"


def test_find_missing_raises(dynamodb_table: Table) -> None:
    with pytest.raises(NotFoundError):
        payrun_repo.find(dynamodb_table, "emp-1", "no-such-run")


def test_create_twice_raises_invalid_state(dynamodb_table: Table) -> None:
    payrun_repo.create(dynamodb_table, _draft())
    with pytest.raises(InvalidStateError):
        payrun_repo.create(dynamodb_table, _draft())


def test_save_draft_requires_draft_status(dynamodb_table: Table) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)
    finalized = payrun_repo.finalize(dynamodb_table, run, rate_table_version=1)

    with pytest.raises(InvalidStateError):
        payrun_repo.save_draft(dynamodb_table, finalized)


def test_finalize_transitions_status_and_locks_version(dynamodb_table: Table) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)

    finalized = payrun_repo.finalize(dynamodb_table, run, rate_table_version=7)
    assert finalized.status == PayRunStatus.FINALIZED
    assert finalized.rate_table_version == 7
    assert finalized.finalized_at is not None

    fetched = payrun_repo.find(dynamodb_table, "emp-1", "run-1")
    assert fetched.status == PayRunStatus.FINALIZED


def test_finalize_twice_raises_invalid_state(dynamodb_table: Table) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)
    payrun_repo.finalize(dynamodb_table, run, rate_table_version=1)

    stale_draft_copy = run  # still says DRAFT in memory
    with pytest.raises(InvalidStateError):
        payrun_repo.finalize(dynamodb_table, stale_draft_copy, rate_table_version=1)


def test_list_for_employer_filters_by_year(dynamodb_table: Table) -> None:
    payrun_repo.create(dynamodb_table, _draft(run_id="run-2026"))
    other_year = _draft(run_id="run-2025")
    other_year = other_year.model_copy(
        update={
            "pay_date": date(2025, 12, 26),
            "period_start": date(2025, 12, 15),
            "period_end": date(2025, 12, 21),
        }
    )
    payrun_repo.create(dynamodb_table, other_year)

    all_runs = payrun_repo.list_for_employer(dynamodb_table, "emp-1")
    assert {r.run_id for r in all_runs} == {"run-2026", "run-2025"}

    only_2026 = payrun_repo.list_for_employer(dynamodb_table, "emp-1", year=2026)
    assert {r.run_id for r in only_2026} == {"run-2026"}
