from datetime import date
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import HourCategory, OvertimePolicy, PayRunStatus
from pappy.models.payrun import ExtraPayLine, HourLine, PayRun, PayRunCreate
from pappy.models.ratetable import RateTable
from pappy.models.ytd import YtdAccumulator
from pappy.money import Money
from pappy.repo import payrun_repo, ytd_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError
from pappy.repo.payrun_repo import _to_item
from tests.factories import make_payroll


def _draft(employer_id: str = "emp-1", run_id: str = "run-1") -> PayRun:
    data = PayRunCreate(
        period_start=date(2026, 1, 5),
        period_end=date(2026, 1, 11),
        pay_date=date(2026, 1, 16),
        hour_lines=[
            HourLine(work_date=date(2026, 1, day), hours=Decimal(9), category=HourCategory.REGULAR)
            for day in range(5, 10)
        ],
    )
    return PayRun.new_draft(
        employer_id=employer_id,
        employee_id="nanny-1",
        run_id=run_id,
        data=data,
        hourly_rate=Decimal("25.00"),
        overtime_policy=OvertimePolicy.APPLIES,
    )


def _finalize(
    dynamodb_table: Table,
    rates_2026: RateTable,
    run: PayRun,
    *,
    prior_ytd: YtdAccumulator | None = None,
) -> tuple[PayRun, YtdAccumulator]:
    return payrun_repo.finalize(
        dynamodb_table,
        run,
        rate_table_version=1,
        payroll=make_payroll(str(run.gross.gross), rates_2026),
        tax_year=2026,
        prior_ytd=prior_ytd,
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


def test_save_draft_requires_draft_status(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)
    finalized, _ = _finalize(dynamodb_table, rates_2026, run)

    with pytest.raises(InvalidStateError):
        payrun_repo.save_draft(dynamodb_table, finalized)


def test_finalize_transitions_status_and_stores_payroll(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)

    finalized, _ = _finalize(dynamodb_table, rates_2026, run)
    assert finalized.status == PayRunStatus.FINALIZED
    assert finalized.rate_table_version == 1
    assert finalized.finalized_at is not None
    assert finalized.payroll is not None
    # gross flows through to the stored computation
    assert finalized.payroll.gross == run.gross.gross

    fetched = payrun_repo.find(dynamodb_table, "emp-1", "run-1")
    assert fetched.status == PayRunStatus.FINALIZED
    assert fetched.payroll is not None
    assert fetched.rate_table_version == 1


def test_finalize_writes_ytd_accumulator_atomically(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)
    assert ytd_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1", 2026) is None

    _, new_ytd = _finalize(dynamodb_table, rates_2026, run)

    stored = ytd_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1", 2026)
    assert stored is not None
    assert stored.social_security_wages == Decimal("1187.50")
    assert stored.medicare_wages == Decimal("1187.50")
    assert stored.futa_wages == Decimal("1187.50")
    assert stored.wa_ui_wages == Decimal("1187.50")
    assert stored.wa_pfml_wages == Decimal("1187.50")
    assert stored.created_at is not None
    # the in-memory mirror matches on every persisted field except the
    # server-side `if_not_exists`/`updated_at` timestamps
    assert new_ytd.social_security_wages == stored.social_security_wages
    assert new_ytd.futa_wages == stored.futa_wages
    assert new_ytd.employee_id == stored.employee_id


def test_finalize_twice_raises_and_never_double_counts(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    run = _draft()
    payrun_repo.create(dynamodb_table, run)
    _finalize(dynamodb_table, rates_2026, run)

    stale_draft_copy = run  # still says DRAFT in memory
    with pytest.raises(InvalidStateError):
        _finalize(dynamodb_table, rates_2026, stale_draft_copy)

    stored = ytd_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1", 2026)
    assert stored is not None
    # The rolled-back transaction left no trace on the accumulator.
    assert stored.social_security_wages == Decimal("1187.50")


def test_finalize_accumulates_across_runs(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    first = _draft(run_id="run-a")
    second = _draft(run_id="run-b").model_copy(update={"pay_date": date(2026, 1, 23)})
    for run in (first, second):
        payrun_repo.create(dynamodb_table, run)

    _, ytd_after_first = _finalize(dynamodb_table, rates_2026, first)
    final_run, ytd_after_second = _finalize(
        dynamodb_table, rates_2026, second, prior_ytd=ytd_after_first
    )

    assert ytd_after_second.social_security_wages == Decimal("2375.00")

    stored = ytd_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1", 2026)
    assert stored is not None
    assert stored.social_security_wages == Decimal("2375.00")
    # identity fields survive; created_at was pinned by the first finalize
    assert stored.employee_id == "nanny-1"
    assert stored.tax_year == 2026
    assert stored.created_at is not None
    assert stored.updated_at is not None
    assert stored.created_at <= stored.updated_at
    assert final_run.payroll is not None


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


def test_reads_a_run_stored_before_extra_pay_existed(dynamodb_table: Table) -> None:
    """Runs persisted by an earlier version must stay readable.

    `GrossPayResult` is stored inside the PayRun item, so a run written before
    extra pay shipped has no `extra_pay` key and no `extra_pay_lines` array. It
    had no extra pay by definition, so the backfill is zero — but it must not
    raise, or every list/get/finalize against the live table would 500.
    """
    item = _to_item(_draft())
    del item["extra_pay_lines"]
    del item["gross"]["extra_pay"]
    dynamodb_table.put_item(Item=item)

    fetched = payrun_repo.get(dynamodb_table, "emp-1", date(2026, 1, 16), "run-1")
    assert fetched.extra_pay_lines == []
    assert str(fetched.gross.extra_pay) == "0.00"
    assert str(fetched.gross.gross) == "1187.50"

    # and it is editable from there like any other draft
    updated = fetched.with_recomputed_pay(
        fetched.hour_lines,
        [ExtraPayLine(note="Bonus", amount=Money("250.00"))],
        hourly_rate=Decimal("25.00"),
        overtime_policy=OvertimePolicy.APPLIES,
    )
    assert str(updated.gross.extra_pay) == "250.00"
    assert str(updated.gross.gross) == "1437.50"
