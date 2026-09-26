"""The core loop end to end at the service layer (design-doc.md §9 Phase 2):
seeded draft -> edit -> finalize, with the finalize transaction advancing YTD
accumulators and wage-base caps holding across runs.

Deterministic expectations use the 2026 rate table: hourly $25, 5x9 schedule
-> $1,187.50 gross. Pub. 15-T (single, standard): annualized $61,750 less the
$8,600 offset = $53,150 -> $5,230 annual -> $100.58 per period.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.calc.fit import MissingW4Error
from pappy.models.common import Address, PayRunStatus
from pappy.models.employee import DefaultScheduleLine, Employee, EmployeeCreate
from pappy.models.employer import Employer, EmployerCreate
from pappy.models.payrun import ExtraPayLine, PayRunCreate
from pappy.models.ratetable import RateTable
from pappy.models.w4 import W4Election
from pappy.money import Money
from pappy.repo import employee_repo, employer_repo, payrun_repo, ytd_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError
from pappy.services import employee_service, payrun_service


def _seed_household(
    dynamodb_table: Table,
    *,
    hourly_rate: str = "25.00",
    weekly_hours: str = "9",
) -> tuple[str, str]:
    employer = employer_repo.put(
        dynamodb_table,
        Employer.new(
            employer_id="emp-1",
            data=EmployerCreate(
                legal_name="Jane Doe",
                ein="12-3456789",
                address=Address(
                    line1="1 Main St", city="Seattle", state="WA", zip_code="98101"
                ),
            ),
        ),
    )
    employee = employee_repo.put(
        dynamodb_table,
        Employee.new(
            employer_id="emp-1",
            employee_id="nanny-1",
            data=EmployeeCreate(
                full_name="Nanny Smith",
                address=Address(
                    line1="2 Elm St", city="Seattle", state="WA", zip_code="98102"
                ),
                hire_date=date(2026, 1, 1),
                hourly_rate=Decimal(hourly_rate),
                default_schedule=[
                    DefaultScheduleLine(weekday=weekday, hours=Decimal(weekly_hours))
                    for weekday in range(5)
                ],
            ),
        ),
    )
    return employer.employer_id, employee.employee_id


def _week(pay_date: date) -> PayRunCreate:
    return PayRunCreate(
        period_start=pay_date - timedelta(days=11),
        period_end=pay_date - timedelta(days=5),
        pay_date=pay_date,
    )


def test_finalize_computes_and_stores_full_payroll(
    dynamodb_table: Table, seeded_rates: RateTable
) -> None:
    employer_id, employee_id = _seed_household(dynamodb_table)
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )

    draft = payrun_service.create_draft(
        dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 16))
    )
    assert draft.payroll is None  # drafts carry gross only

    finalized = payrun_service.finalize_run(dynamodb_table, employer_id, draft.run_id)
    payroll = finalized.payroll
    assert payroll is not None

    # deterministic golden values for the 2026 table at $1,187.50 gross
    assert str(payroll.gross) == "1187.50"
    assert str(payroll.withholding.social_security) == "73.63"
    assert str(payroll.withholding.medicare) == "17.22"
    assert str(payroll.withholding.additional_medicare) == "0.00"
    assert str(payroll.withholding.federal_income_tax) == "100.58"
    assert str(payroll.withholding.wa_pfml_employee) == "9.59"
    assert str(payroll.withholding.wa_cares_employee) == "6.89"
    assert str(payroll.net_pay) == "979.59"

    accruals = payroll.employer_accruals
    assert str(accruals.social_security) == "73.63"
    assert str(accruals.medicare) == "17.22"
    assert str(accruals.futa) == "7.13"
    assert str(accruals.wa_ui) == "0.00"  # no ESD experience rate entered yet
    assert str(accruals.wa_pfml_employer) == "0.00"  # household employers are exempt

    # net + withholding ≡ gross (§8 property), through the stored artifact
    assert payroll.net_pay + payroll.withholding.total == payroll.gross
    assert finalized.rate_table_version == seeded_rates.version

    stored = payrun_repo.find(dynamodb_table, employer_id, finalized.run_id)
    assert stored.payroll == payroll


def test_finalize_advances_ytd_accumulator(
    dynamodb_table: Table, seeded_rates: RateTable
) -> None:
    employer_id, employee_id = _seed_household(dynamodb_table)
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )

    draft = payrun_service.create_draft(
        dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 16))
    )
    payrun_service.finalize_run(dynamodb_table, employer_id, draft.run_id)

    ytd = ytd_repo.get_or_none(dynamodb_table, employer_id, employee_id, 2026)
    assert ytd is not None
    assert ytd.social_security_wages == Decimal("1187.50")
    assert ytd.futa_wages == Decimal("1187.50")


def test_futa_wage_base_caps_across_runs(dynamodb_table: Table, seeded_rates: RateTable) -> None:
    # $200/h x 40h = $8,000/week crosses the $7,000 FUTA base on run one.
    employer_id, employee_id = _seed_household(dynamodb_table, hourly_rate="200.00", weekly_hours="8")
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )

    first = payrun_service.finalize_run(
        dynamodb_table,
        employer_id,
        payrun_service.create_draft(
            dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 16))
        ).run_id,
    )
    second = payrun_service.finalize_run(
        dynamodb_table,
        employer_id,
        payrun_service.create_draft(
            dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 23))
        ).run_id,
    )

    assert first.payroll is not None and second.payroll is not None
    assert str(first.payroll.taxable.futa) == "7000"
    assert str(first.payroll.employer_accruals.futa) == "42.00"
    assert str(second.payroll.taxable.futa) == "0"
    assert str(second.payroll.employer_accruals.futa) == "0.00"

    ytd = ytd_repo.get_or_none(dynamodb_table, employer_id, employee_id, 2026)
    assert ytd is not None
    assert ytd.futa_wages == Decimal(7000)  # capped, not 15,000 of gross
    assert ytd.social_security_wages == Decimal(16000)  # SS base not reached


def test_mid_year_w4_change_applies_only_to_later_runs(
    dynamodb_table: Table, seeded_rates: RateTable
) -> None:
    employer_id, employee_id = _seed_household(dynamodb_table)
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )
    june = payrun_service.finalize_run(
        dynamodb_table,
        employer_id,
        payrun_service.create_draft(
            dynamodb_table, employer_id, employee_id, _week(date(2026, 6, 19))
        ).run_id,
    )
    # re-election effective July: adds $100/period extra withholding
    employee_service.add_w4_election(
        dynamodb_table,
        employer_id,
        employee_id,
        W4Election(effective_date=date(2026, 7, 1), extra_withholding=Decimal("100.00")),
    )
    august = payrun_service.finalize_run(
        dynamodb_table,
        employer_id,
        payrun_service.create_draft(
            dynamodb_table, employer_id, employee_id, _week(date(2026, 8, 7))
        ).run_id,
    )

    assert june.payroll is not None and august.payroll is not None
    june_fit = june.payroll.withholding.federal_income_tax
    august_fit = august.payroll.withholding.federal_income_tax
    assert str(august_fit - june_fit) == "100.00"


def test_finalize_without_w4_blocks(dynamodb_table: Table, seeded_rates: RateTable) -> None:
    employer_id, employee_id = _seed_household(dynamodb_table)
    draft = payrun_service.create_draft(
        dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 16))
    )

    with pytest.raises(MissingW4Error):
        payrun_service.finalize_run(dynamodb_table, employer_id, draft.run_id)

    # nothing was written
    stored = payrun_repo.find(dynamodb_table, employer_id, draft.run_id)
    assert stored.status == PayRunStatus.DRAFT
    assert ytd_repo.get_or_none(dynamodb_table, employer_id, employee_id, 2026) is None


def test_finalize_without_rate_table_blocks(dynamodb_table: Table) -> None:
    employer_id, employee_id = _seed_household(dynamodb_table)
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )
    draft = payrun_service.create_draft(
        dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 16))
    )

    with pytest.raises(NotFoundError):
        payrun_service.finalize_run(dynamodb_table, employer_id, draft.run_id)

    stored = payrun_repo.find(dynamodb_table, employer_id, draft.run_id)
    assert stored.status == PayRunStatus.DRAFT


def test_extra_pay_draft_edit_then_finalize(
    dynamodb_table: Table, seeded_rates: RateTable
) -> None:
    """A flat lump sum added to a DRAFT, then locked in at finalization."""
    employer_id, employee_id = _seed_household(dynamodb_table)
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )

    draft = payrun_service.create_draft(
        dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 16))
    )
    assert str(draft.gross.gross) == "1187.50"
    assert str(draft.gross.extra_pay) == "0.00"

    updated = payrun_service.update_draft(
        dynamodb_table,
        employer_id,
        draft.run_id,
        draft.hour_lines,
        [ExtraPayLine(note="Holiday bonus", amount=Money("250.00"))],
    )
    assert str(updated.gross.extra_pay) == "250.00"
    assert str(updated.gross.gross) == "1437.50"
    assert updated.payroll is None  # still a draft: nothing withheld yet

    finalized = payrun_service.finalize_run(dynamodb_table, employer_id, draft.run_id)
    payroll = finalized.payroll
    assert payroll is not None
    # same golden as tests/calc/test_payroll.py::TestExtraPayGolden
    assert str(payroll.gross) == "1437.50"
    assert str(payroll.withholding.federal_income_tax) == "146.44"
    assert str(payroll.withholding.social_security) == "89.13"
    assert str(payroll.withholding.medicare) == "20.84"
    assert str(payroll.net_pay) == "1161.15"
    assert payroll.net_pay + payroll.withholding.total == payroll.gross

    # the bonus advanced the YTD wage accumulators like any other wage
    ytd = ytd_repo.get_or_none(dynamodb_table, employer_id, employee_id, 2026)
    assert ytd is not None
    assert str(ytd.social_security_wages) == "1437.50"
    assert str(ytd.futa_wages) == "1437.50"

    # a finalized run is immutable: the bonus can no longer be edited
    with pytest.raises(InvalidStateError):
        payrun_service.update_draft(
            dynamodb_table,
            employer_id,
            draft.run_id,
            finalized.hour_lines,
            [ExtraPayLine(note="Second bonus", amount=Money("500.00"))],
        )


def test_extra_pay_does_not_leak_into_a_later_run(
    dynamodb_table: Table, seeded_rates: RateTable
) -> None:
    """The bonus is per-run — the next week is back to hours-only gross."""
    employer_id, employee_id = _seed_household(dynamodb_table)
    employee_service.add_w4_election(
        dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1))
    )

    first = payrun_service.create_draft(
        dynamodb_table,
        employer_id,
        employee_id,
        _week(date(2026, 1, 16)).model_copy(
            update={"extra_pay_lines": [ExtraPayLine(note="Bonus", amount=Money("250.00"))]}
        ),
    )
    payrun_service.finalize_run(dynamodb_table, employer_id, first.run_id)

    second = payrun_service.create_draft(
        dynamodb_table, employer_id, employee_id, _week(date(2026, 1, 23))
    )
    assert str(second.gross.extra_pay) == "0.00"
    assert str(second.gross.gross) == "1187.50"
    assert second.extra_pay_lines == []
