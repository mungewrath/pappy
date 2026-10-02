"""Year view and CSV export (design-doc.md §6.2).

Two layers, deliberately separate:

- `TestBuildYearView` / `TestYearViewCsv` drive the pure aggregation, so the
  running-total arithmetic, the finalized-only rule, and the CSV's numeric
  fidelity are tested without a database;
- `TestYearViewService` covers the database half — the sort-key date range
  (§4) and the stored CSV artifact.

Hours follow the existing 45-hour golden week (5x9 at $25), which the
2026 table prices at $1,187.50 gross: 45 straight-time hours at $25 plus the
0.5x premium on the 5 hours over the 40-hour threshold.
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.calc.payroll import compute_payroll
from pappy.calc.year_view import CSV_COLUMNS, build_year_view, finalized_runs, year_view_csv
from pappy.models.common import Address, OvertimePolicy, PayRunStatus
from pappy.models.document import DocumentType
from pappy.models.employee import DefaultScheduleLine, Employee, EmployeeCreate
from pappy.models.employer import Employer, EmployerCreate
from pappy.models.payrun import ExtraPayLine, HourLine, PayRun, PayRunCreate
from pappy.models.ratetable import RateTable
from pappy.models.w4 import W4Election
from pappy.models.year_view import YearView
from pappy.money import Money
from pappy.repo import document_repo, employee_repo, employer_repo, payrun_repo
from pappy.repo.bucket import get_bucket
from pappy.services import employee_service, payrun_service, year_view_service

EMPLOYER_ID = "emp-1"
EMPLOYEE_ID = "nanny-1"
NAMES = {EMPLOYEE_ID: "Nanny Smith"}

WEEKLY_GROSS = Money("1187.50")
STRAIGHT_TIME = Money("1125.00")
OVERTIME_PREMIUM = Money("62.50")


def _make_run(
    pay_date: date,
    rates: RateTable,
    *,
    status: PayRunStatus = PayRunStatus.FINALIZED,
    extra_pay: str | None = None,
    employee_id: str = EMPLOYEE_ID,
) -> PayRun:
    """A pay run with a real stored `PayrollResult`.

    Built through the same `PayRun` constructors the service layer uses, so
    the aggregation under test reads the shapes it will actually see. Five
    9-hour days cross the 40-hour threshold, producing 5 overtime hours.
    """
    data = PayRunCreate(
        period_start=pay_date - timedelta(days=11),
        period_end=pay_date - timedelta(days=5),
        pay_date=pay_date,
        hour_lines=[
            HourLine(work_date=pay_date - timedelta(days=offset), hours=Decimal(9))
            for offset in range(4, -1, -1)
        ],
        extra_pay_lines=(
            [ExtraPayLine(note="Bonus", amount=Money(extra_pay))] if extra_pay else []
        ),
    )
    draft = PayRun.new_draft(
        employer_id=EMPLOYER_ID,
        employee_id=employee_id,
        run_id=f"run-{employee_id}-{pay_date.isoformat()}",
        data=data,
        hourly_rate=Decimal("25.00"),
        overtime_policy=OvertimePolicy.APPLIES,
    )
    if status != PayRunStatus.FINALIZED:
        return draft
    payroll = compute_payroll(
        gross=draft.gross.gross,
        w4=W4Election(effective_date=date(2026, 1, 1)),
        rates=rates,
    )
    return draft.finalize(rate_table_version=rates.version, payroll=payroll)


class TestBuildYearView:
    def test_rows_are_finalized_runs_only(self, rates_2026: RateTable) -> None:
        finalized = _make_run(date(2026, 1, 16), rates_2026)
        draft = _make_run(date(2026, 1, 23), rates_2026, status=PayRunStatus.DRAFT)

        assert finalized_runs([finalized, draft]) == [finalized]

    def test_voided_runs_are_excluded(self, rates_2026: RateTable) -> None:
        finalized = _make_run(date(2026, 1, 16), rates_2026)
        voided = _make_run(date(2026, 1, 23), rates_2026).void()

        assert finalized_runs([finalized, voided]) == [finalized]

    def test_running_ytd_totals_accumulate_in_pay_date_order(
        self, rates_2026: RateTable
    ) -> None:
        runs = [
            _make_run(date(2026, 2, 13), rates_2026),
            _make_run(date(2026, 1, 16), rates_2026),
            _make_run(date(2026, 1, 23), rates_2026),
        ]
        view = build_year_view(runs, tax_year=2026, employee_names=NAMES)

        assert [row.pay_date for row in view.rows] == [
            date(2026, 1, 16),
            date(2026, 1, 23),
            date(2026, 2, 13),
        ]
        first, second, third = view.rows
        # Each row's YTD is the running total *including* that row.
        assert first.ytd_gross == first.gross
        assert second.ytd_gross == first.gross + second.gross
        assert third.ytd_gross == second.ytd_gross + third.gross
        assert third.ytd_net_pay == first.net_pay + second.net_pay + third.net_pay

    def test_totals_equal_the_last_running_total(self, rates_2026: RateTable) -> None:
        view = build_year_view(
            [
                _make_run(date(2026, 1, 16), rates_2026),
                _make_run(date(2026, 1, 23), rates_2026),
            ],
            tax_year=2026,
            employee_names=NAMES,
        )
        last = view.rows[-1]
        assert view.totals.gross == last.ytd_gross
        assert view.totals.net_pay == last.ytd_net_pay
        assert view.totals.total_withholding == last.ytd_total_withholding
        assert view.totals.finalized_run_count == 2

    def test_runs_outside_the_tax_year_are_excluded(self, rates_2026: RateTable) -> None:
        runs = [
            _make_run(date(2026, 1, 16), rates_2026),
            _make_run(date(2025, 12, 19), rates_2026),
        ]
        view = build_year_view(runs, tax_year=2026, employee_names=NAMES)
        assert [row.pay_date for row in view.rows] == [date(2026, 1, 16)]

    def test_employee_filter_applies_before_accumulation(
        self, rates_2026: RateTable
    ) -> None:
        runs = [
            _make_run(date(2026, 1, 16), rates_2026),
            _make_run(date(2026, 1, 23), rates_2026, employee_id="nanny-2"),
        ]
        view = build_year_view(
            runs, tax_year=2026, employee_names=NAMES, employee_id=EMPLOYEE_ID
        )
        # The running total describes the filtered set, not the whole year —
        # a filtered total counting another employee's wages would be meaningless.
        assert len(view.rows) == 1
        assert view.rows[0].ytd_gross == view.rows[0].gross

    def test_empty_year_is_zero_filled(self) -> None:
        view = build_year_view([], tax_year=2026, employee_names=NAMES)
        assert view.rows == []
        assert view.totals.finalized_run_count == 0
        assert view.totals.gross.amount == 0

    def test_overtime_and_extra_pay_are_broken_out(self, rates_2026: RateTable) -> None:
        run = _make_run(date(2026, 1, 16), rates_2026, extra_pay="250.00")
        row = build_year_view([run], tax_year=2026, employee_names=NAMES).rows[0]

        # §5.4: straight-time and the 0.5x premium are separate lines, so an
        # overtime question is answerable from the archive without recomputing.
        assert row.regular_hours == Decimal(45)
        assert row.overtime_hours == Decimal(5)
        assert row.straight_time_pay == STRAIGHT_TIME
        assert row.overtime_premium_pay == OVERTIME_PREMIUM
        assert row.extra_pay == Money("250.00")
        assert row.gross == Money("1437.50")

    def test_row_figures_come_from_the_stored_computation(
        self, rates_2026: RateTable
    ) -> None:
        run = _make_run(date(2026, 1, 16), rates_2026)
        assert run.payroll is not None
        row = build_year_view([run], tax_year=2026, employee_names=NAMES).rows[0]

        # "Compute once, store the result" — the year view reads the finalized
        # run's stored numbers, it does not re-derive them.
        assert row.gross == run.payroll.gross
        assert row.net_pay == run.payroll.net_pay
        assert row.withholding == run.payroll.withholding
        assert row.employer_accruals == run.payroll.employer_accruals

    def test_unknown_employee_falls_back_to_id(self, rates_2026: RateTable) -> None:
        run = _make_run(date(2026, 1, 16), rates_2026)
        row = build_year_view([run], tax_year=2026, employee_names={}).rows[0]
        assert row.employee_name == EMPLOYEE_ID


class TestYearViewCsv:
    def _csv_rows(self, view: YearView) -> list[list[str]]:
        return list(csv.reader(io.StringIO(year_view_csv(view).decode("utf-8"))))

    def test_header_matches_declared_columns_in_order(self, rates_2026: RateTable) -> None:
        view = build_year_view(
            [_make_run(date(2026, 1, 16), rates_2026)], tax_year=2026, employee_names=NAMES
        )
        assert self._csv_rows(view)[0] == [label for _key, label in CSV_COLUMNS]

    def test_money_is_written_as_an_exact_decimal_string(
        self, rates_2026: RateTable
    ) -> None:
        run = _make_run(date(2026, 1, 16), rates_2026)
        assert run.payroll is not None
        view = build_year_view([run], tax_year=2026, employee_names=NAMES)
        header, data = self._csv_rows(view)[0], self._csv_rows(view)[1]
        gross_cell = data[header.index("Gross pay")]

        # No currency symbol, no thousands separator, no float rounding —
        # §5.5 requires the stored value to stay byte-identical to the ledger.
        assert gross_cell == str(run.payroll.gross.amount)
        assert "$" not in gross_cell and "," not in gross_cell
        assert Decimal(gross_cell) == run.payroll.gross.amount

    def test_every_row_has_the_full_column_count(self, rates_2026: RateTable) -> None:
        view = build_year_view(
            [
                _make_run(date(2026, 1, 16), rates_2026),
                _make_run(date(2026, 1, 23), rates_2026, extra_pay="100.00"),
            ],
            tax_year=2026,
            employee_names=NAMES,
        )
        assert all(len(row) == len(CSV_COLUMNS) for row in self._csv_rows(view))

    def test_total_row_carries_the_year_totals(self, rates_2026: RateTable) -> None:
        view = build_year_view(
            [
                _make_run(date(2026, 1, 16), rates_2026),
                _make_run(date(2026, 1, 23), rates_2026),
            ],
            tax_year=2026,
            employee_names=NAMES,
        )
        header, total = self._csv_rows(view)[0], self._csv_rows(view)[-1]
        assert total[0] == "TOTAL"
        assert Decimal(total[header.index("Gross pay")]) == view.totals.gross.amount
        assert Decimal(total[header.index("Net pay")]) == view.totals.net_pay.amount
        # Non-money columns stay blank so the row keeps the column count.
        assert total[header.index("Regular hours")] == ""

    def test_one_data_row_per_run_plus_a_total(self, rates_2026: RateTable) -> None:
        view = build_year_view(
            [
                _make_run(date(2026, 1, 16), rates_2026),
                _make_run(date(2026, 1, 23), rates_2026),
            ],
            tax_year=2026,
            employee_names=NAMES,
        )
        assert len(self._csv_rows(view)) == 4  # header + 2 runs + total

    def test_csv_uses_crlf_line_endings(self, rates_2026: RateTable) -> None:
        view = build_year_view(
            [_make_run(date(2026, 1, 16), rates_2026)], tax_year=2026, employee_names=NAMES
        )
        assert b"\r\n" in year_view_csv(view)

    def test_employee_name_with_a_comma_is_quoted(self, rates_2026: RateTable) -> None:
        run = _make_run(date(2026, 1, 16), rates_2026)
        view = build_year_view(
            [run], tax_year=2026, employee_names={EMPLOYEE_ID: "Smith, Nanny"}
        )
        assert self._csv_rows(view)[1][3] == "Smith, Nanny"


@pytest.fixture
def local_documents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the local document transport at a temp directory.

    Without this, an export would write into `./documents` relative to the
    test process's working directory and leak between test runs.
    """
    directory = tmp_path / "documents"
    monkeypatch.setenv("PAPPY_DOCUMENTS_DIR", str(directory))
    monkeypatch.delenv("PAPPY_DOCUMENTS_BUCKET_NAME", raising=False)
    return directory


def _seed_household(table: Table) -> None:
    employer_repo.put(
        table,
        Employer.new(
            employer_id=EMPLOYER_ID,
            data=EmployerCreate(
                legal_name="Jane Doe",
                ein="12-3456789",
                address=Address(
                    line1="1 Main St", city="Seattle", state="WA", zip_code="98101"
                ),
            ),
        ),
    )
    employee_repo.put(
        table,
        Employee.new(
            employer_id=EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            data=EmployeeCreate(
                full_name="Nanny Smith",
                address=Address(
                    line1="2 Elm St", city="Seattle", state="WA", zip_code="98102"
                ),
                hire_date=date(2026, 1, 1),
                hourly_rate=Decimal("25.00"),
                default_schedule=[
                    DefaultScheduleLine(weekday=weekday, hours=Decimal(9))
                    for weekday in range(5)
                ],
            ),
        ),
    )
    # Effective from the start of 2025 so a run dated in either year resolves.
    # The election's contents are the defaults, so the date changes nothing
    # about the amounts — it only decides which periods have a W-4 at all.
    employee_service.add_w4_election(
        table, EMPLOYER_ID, EMPLOYEE_ID, W4Election(effective_date=date(2025, 1, 1))
    )


def _finalize_week(table: Table, pay_date: date) -> str:
    """Create and finalize one 45-hour week through the real service path."""
    draft = payrun_service.create_draft(
        table,
        EMPLOYER_ID,
        EMPLOYEE_ID,
        PayRunCreate(
            period_start=pay_date - timedelta(days=11),
            period_end=pay_date - timedelta(days=5),
            pay_date=pay_date,
        ),
    )
    return payrun_service.finalize_run(table, EMPLOYER_ID, draft.run_id).run_id


class TestYearViewService:
    def test_returns_finalized_runs_for_the_year(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        _finalize_week(dynamodb_table, date(2026, 1, 23))

        view = year_view_service.year_view(dynamodb_table, EMPLOYER_ID, tax_year=2026)
        assert view.totals.finalized_run_count == 2
        assert view.rows[0].employee_name == "Nanny Smith"
        assert view.rows[0].gross == WEEKLY_GROSS

    def test_date_range_is_inclusive_on_both_ends(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        for pay_date in (date(2026, 1, 16), date(2026, 1, 23), date(2026, 1, 30)):
            _finalize_week(dynamodb_table, pay_date)

        view = year_view_service.year_view(
            dynamodb_table,
            EMPLOYER_ID,
            tax_year=2026,
            start=date(2026, 1, 16),
            end=date(2026, 1, 23),
        )
        # Both boundary runs land inside the range — the sort-key upper bound
        # has to sort after every run id on the end date, not equal to it.
        assert [row.pay_date for row in view.rows] == [
            date(2026, 1, 16),
            date(2026, 1, 23),
        ]
        assert view.period_start == date(2026, 1, 16)
        assert view.period_end == date(2026, 1, 23)

    def test_range_totals_cover_only_the_filtered_runs(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        for pay_date in (date(2026, 1, 16), date(2026, 1, 23), date(2026, 1, 30)):
            _finalize_week(dynamodb_table, pay_date)

        view = year_view_service.year_view(
            dynamodb_table,
            EMPLOYER_ID,
            tax_year=2026,
            start=date(2026, 1, 16),
            end=date(2026, 1, 16),
        )
        assert view.totals.gross == WEEKLY_GROSS

    def test_drafts_are_excluded(self, dynamodb_table: Table, seeded_rates: RateTable) -> None:
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        payrun_service.create_draft(
            dynamodb_table,
            EMPLOYER_ID,
            EMPLOYEE_ID,
            PayRunCreate(
                period_start=date(2026, 1, 26),
                period_end=date(2026, 2, 1),
                pay_date=date(2026, 2, 6),
            ),
        )

        view = year_view_service.year_view(dynamodb_table, EMPLOYER_ID, tax_year=2026)
        assert view.totals.finalized_run_count == 1

    def test_export_stores_a_hashed_csv_document(
        self,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir  # applied via env; referenced for ordering
        _seed_household(dynamodb_table)
        run_ids = [
            _finalize_week(dynamodb_table, date(2026, 1, 16)),
            _finalize_week(dynamodb_table, date(2026, 1, 23)),
        ]

        doc = year_view_service.export_year_view_csv(
            dynamodb_table, EMPLOYER_ID, tax_year=2026
        )
        assert doc.document_type == DocumentType.YEAR_VIEW_CSV
        assert doc.tax_year == 2026
        assert doc.filename.endswith(".csv")
        assert sorted(doc.pay_run_ids) == sorted(run_ids)
        assert len(doc.sha256) == 64

        stored = get_bucket().local_path(doc.s3_key).read_bytes()
        assert hashlib.sha256(stored).hexdigest() == doc.sha256
        assert stored.decode("utf-8").startswith("Pay date,Period start")

    def test_export_is_discoverable_in_the_document_archive(
        self,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir  # applied via env; referenced for ordering
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        doc = year_view_service.export_year_view_csv(
            dynamodb_table, EMPLOYER_ID, tax_year=2026
        )
        found = document_repo.list_for_employer(
            dynamodb_table,
            EMPLOYER_ID,
            tax_year=2026,
            doc_type=DocumentType.YEAR_VIEW_CSV,
        )
        assert [d.doc_id for d in found] == [doc.doc_id]

    def test_export_records_the_filtered_period(
        self,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir  # applied via env; referenced for ordering
        _seed_household(dynamodb_table)
        for pay_date in (date(2026, 1, 16), date(2026, 1, 23), date(2026, 1, 30)):
            _finalize_week(dynamodb_table, pay_date)

        doc = year_view_service.export_year_view_csv(
            dynamodb_table,
            EMPLOYER_ID,
            tax_year=2026,
            start=date(2026, 1, 16),
            end=date(2026, 1, 23),
        )
        assert doc.period_start == date(2026, 1, 16)
        assert doc.period_end == date(2026, 1, 23)
        assert len(doc.pay_run_ids) == 2

    def test_each_export_is_its_own_artifact(
        self,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir  # applied via env; referenced for ordering
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        first = year_view_service.export_year_view_csv(
            dynamodb_table, EMPLOYER_ID, tax_year=2026
        )
        second = year_view_service.export_year_view_csv(
            dynamodb_table, EMPLOYER_ID, tax_year=2026
        )
        # Same filters over unchanged data hash identically, but they stay
        # separate documents: being able to evidence what was actually sent
        # to an accountant is the point of storing the export.
        assert first.doc_id != second.doc_id
        assert first.sha256 == second.sha256

    def test_year_view_is_scoped_to_the_employer(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        view = year_view_service.year_view(dynamodb_table, "someone-else", tax_year=2026)
        assert view.rows == []


class TestPayrunRangeFilter:
    def test_reversed_range_is_rejected(self, dynamodb_table: Table) -> None:
        with pytest.raises(ValueError, match="start must not be after end"):
            payrun_repo.list_for_employer(
                dynamodb_table, EMPLOYER_ID, start=date(2026, 1, 23), end=date(2026, 1, 16)
            )

    def test_year_and_range_must_agree(self, dynamodb_table: Table) -> None:
        with pytest.raises(ValueError, match="not within tax year"):
            payrun_repo.list_for_employer(
                dynamodb_table,
                EMPLOYER_ID,
                year=2026,
                start=date(2025, 12, 1),
                end=date(2026, 1, 5),
            )

    def test_start_without_end_is_rejected(self, dynamodb_table: Table) -> None:
        with pytest.raises(ValueError, match="must be given together"):
            payrun_repo.list_for_employer(
                dynamodb_table, EMPLOYER_ID, start=date(2026, 1, 1)
            )

    def test_end_without_start_is_rejected(self, dynamodb_table: Table) -> None:
        with pytest.raises(ValueError, match="must be given together"):
            payrun_repo.list_for_employer(dynamodb_table, EMPLOYER_ID, end=date(2026, 1, 1))

    def test_range_sees_runs_written_by_the_normal_path(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        _finalize_week(dynamodb_table, date(2026, 3, 20))

        runs = payrun_repo.list_for_employer(
            dynamodb_table, EMPLOYER_ID, start=date(2026, 3, 1), end=date(2026, 3, 31)
        )
        assert [r.pay_date for r in runs] == [date(2026, 3, 20)]
        assert runs[0].status == PayRunStatus.FINALIZED

    def test_year_prefix_still_works_without_a_range(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        _finalize_week(dynamodb_table, date(2026, 3, 20))

        assert len(payrun_repo.list_for_employer(dynamodb_table, EMPLOYER_ID, year=2026)) == 2
        assert len(payrun_repo.list_for_employer(dynamodb_table, EMPLOYER_ID, year=2025)) == 0
        assert len(payrun_repo.list_for_employer(dynamodb_table, EMPLOYER_ID)) == 2

    def test_range_may_span_a_year_boundary(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed_household(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        _finalize_week(dynamodb_table, date(2026, 3, 20))

        # A range is a sort-key range, not a year prefix, so it is not
        # restricted to one tax year — this is what lets an employer pull
        # "November through March" for a year-over-year comparison.
        runs = payrun_repo.list_for_employer(
            dynamodb_table, EMPLOYER_ID, start=date(2025, 11, 1), end=date(2026, 1, 31)
        )
        assert [r.pay_date for r in runs] == [date(2026, 1, 16)]
