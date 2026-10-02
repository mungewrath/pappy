"""Year-view aggregation and CSV rendering (design-doc.md §6.2).

Pure calculation, no AWS imports — the service layer supplies the finalized
runs and this module turns them into the audit table and its CSV export.

The running YTD columns are accumulated here, in one pass, in `Money`:
quantized per line and added as `Decimal`, never as float (§5.5). That is the
whole reason this lives server-side — the SPA receives the running totals as
exact strings and only formats them.

Money in the CSV is written as the exact decimal string the ledger holds
("1234.56"), with no currency symbol, thousands separator, or trailing
percent: the export is an audit artifact meant to be re-imported and compared,
and §5.5 requires the stored value to stay byte-identical to what was
computed.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

from pappy.models.common import PayRunStatus
from pappy.models.payrun import PayRun
from pappy.models.year_view import YearView, YearViewRow, YearViewTotals
from pappy.money import Money

# Column order is the CSV's contract: the on-screen table and the export
# present the same figures left to right, so a reader moving between them is
# never looking at a different column under the same heading.
CSV_COLUMNS: tuple[tuple[str, str], ...] = (
    ("pay_date", "Pay date"),
    ("period_start", "Period start"),
    ("period_end", "Period end"),
    ("employee_name", "Employee"),
    ("regular_hours", "Regular hours"),
    ("overtime_hours", "Overtime hours"),
    ("other_paid_hours", "Other paid hours"),
    ("unpaid_hours", "Unpaid hours"),
    ("straight_time_pay", "Straight-time pay"),
    ("overtime_premium_pay", "Overtime premium"),
    ("extra_pay", "Extra pay"),
    ("gross", "Gross pay"),
    ("social_security", "Social Security"),
    ("medicare", "Medicare"),
    ("additional_medicare", "Additional Medicare"),
    ("federal_income_tax", "Federal income tax"),
    ("wa_pfml_employee", "WA PFML"),
    ("wa_cares_employee", "WA Cares"),
    ("total_withholding", "Total withholding"),
    ("net_pay", "Net pay"),
    ("er_social_security", "ER Social Security"),
    ("er_medicare", "ER Medicare"),
    ("futa", "FUTA"),
    ("wa_ui", "WA UI"),
    ("wa_pfml_employer", "ER WA PFML"),
    ("ytd_gross", "YTD gross"),
    ("ytd_total_withholding", "YTD withholding"),
    ("ytd_net_pay", "YTD net pay"),
)


def finalized_runs(runs: list[PayRun]) -> list[PayRun]:
    """Keep only runs the year view is allowed to show.

    §6.2 says the year view lists every *finalized* run. Drafts have no
    stored computation, so including them would mean blank money columns and
    a running total that moves as the employer edits; a voided run is
    excluded because its wages are not wages. Drafts remain visible in the
    pay-run list, which is where an in-progress week belongs.
    """
    return [
        run
        for run in runs
        if run.status == PayRunStatus.FINALIZED and run.payroll is not None
    ]


def build_year_view(
    runs: list[PayRun],
    *,
    tax_year: int,
    employee_names: dict[str, str],
    period_start: date | None = None,
    period_end: date | None = None,
    employee_id: str | None = None,
) -> YearView:
    """Build the §6.2 year view from finalized runs.

    Rows are ordered by pay date, and the YTD columns are a running total in
    that order — so the final row's `ytd_*` is the year total, and the
    `totals` block is that same value rather than a second accumulation that
    could disagree with it.

    The employee filter is applied *before* accumulation, so a filtered view's
    running totals describe the filtered set. That is the useful reading for
    "what did this employee earn between these dates", and a filtered total
    that still counted other employees' wages would be meaningless.
    """
    selected = [run for run in finalized_runs(runs) if run.pay_date.year == tax_year]
    if employee_id is not None:
        selected = [run for run in selected if run.employee_id == employee_id]
    selected.sort(key=lambda r: (r.pay_date, r.run_id))

    rows: list[YearViewRow] = []
    ytd_gross = Money.zero
    ytd_withholding = Money.zero
    ytd_net = Money.zero

    for run in selected:
        payroll = run.payroll
        assert payroll is not None  # guaranteed by finalized_runs
        gross = run.gross
        withholding_total = payroll.withholding.total

        ytd_gross = ytd_gross + payroll.gross
        ytd_withholding = ytd_withholding + withholding_total
        ytd_net = ytd_net + payroll.net_pay

        rows.append(
            YearViewRow(
                run_id=run.run_id,
                pay_date=run.pay_date,
                period_start=run.period_start,
                period_end=run.period_end,
                employee_id=run.employee_id,
                employee_name=employee_names.get(run.employee_id, run.employee_id),
                regular_hours=gross.regular_hours,
                overtime_hours=gross.overtime_hours,
                other_paid_hours=gross.other_paid_hours,
                unpaid_hours=gross.unpaid_hours,
                straight_time_pay=gross.straight_time_pay,
                overtime_premium_pay=gross.overtime_premium_pay,
                extra_pay=gross.extra_pay,
                gross=payroll.gross,
                withholding=payroll.withholding,
                total_withholding=withholding_total,
                net_pay=payroll.net_pay,
                employer_accruals=payroll.employer_accruals,
                ytd_gross=ytd_gross,
                ytd_total_withholding=ytd_withholding,
                ytd_net_pay=ytd_net,
            )
        )

    totals = YearViewTotals(
        finalized_run_count=len(rows),
        gross=ytd_gross,
        total_withholding=ytd_withholding,
        net_pay=ytd_net,
        ytd_gross=ytd_gross,
        ytd_total_withholding=ytd_withholding,
        ytd_net_pay=ytd_net,
    )
    return YearView(
        tax_year=tax_year,
        period_start=period_start,
        period_end=period_end,
        employee_id=employee_id,
        rows=rows,
        totals=totals,
    )


def _csv_cell(row: YearViewRow, column: str) -> str:
    """One CSV cell as an exact string — never a formatted float."""
    withholding = row.withholding
    accruals = row.employer_accruals
    money_fields = {
        "straight_time_pay": row.straight_time_pay,
        "overtime_premium_pay": row.overtime_premium_pay,
        "extra_pay": row.extra_pay,
        "gross": row.gross,
        "social_security": withholding.social_security,
        "medicare": withholding.medicare,
        "additional_medicare": withholding.additional_medicare,
        "federal_income_tax": withholding.federal_income_tax,
        "wa_pfml_employee": withholding.wa_pfml_employee,
        "wa_cares_employee": withholding.wa_cares_employee,
        "total_withholding": row.total_withholding,
        "net_pay": row.net_pay,
        "er_social_security": accruals.social_security,
        "er_medicare": accruals.medicare,
        "futa": accruals.futa,
        "wa_ui": accruals.wa_ui,
        "wa_pfml_employer": accruals.wa_pfml_employer,
        "ytd_gross": row.ytd_gross,
        "ytd_total_withholding": row.ytd_total_withholding,
        "ytd_net_pay": row.ytd_net_pay,
    }
    if column in money_fields:
        return str(money_fields[column].amount)
    if column in ("pay_date", "period_start", "period_end"):
        value: date = getattr(row, column)
        return value.isoformat()
    if column == "employee_name":
        return row.employee_name
    hours: Decimal = getattr(row, column)
    return str(hours)


def year_view_csv(view: YearView) -> bytes:
    """Render the year view as CSV bytes.

    UTF-8 with CRLF line endings and a trailing total row, so the file opens
    cleanly in a spreadsheet and still carries the year's totals for anyone
    reading it as text. A total row whose figures are blank for the
    hour/date columns keeps the column count aligned.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow([label for _key, label in CSV_COLUMNS])

    for row in view.rows:
        writer.writerow([_csv_cell(row, key) for key, _label in CSV_COLUMNS])

    totals = view.totals
    # The six money columns the total row carries; every other column is
    # blank in that row so the column count still lines up.
    total_keys = {
        "gross",
        "total_withholding",
        "net_pay",
        "ytd_gross",
        "ytd_total_withholding",
        "ytd_net_pay",
    }
    total_cells: list[str] = []
    for key, _label in CSV_COLUMNS:
        if key in total_keys:
            total_cells.append(str(getattr(totals, key).amount))
        else:
            total_cells.append("")
    total_cells[0] = "TOTAL"
    writer.writerow(total_cells)

    return buffer.getvalue().encode("utf-8")
