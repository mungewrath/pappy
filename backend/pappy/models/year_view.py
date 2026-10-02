"""Year-view schemas — the audit table and its CSV export (design-doc.md §6.2).

Every money field is a `Money`, serialized as an exact decimal string (§5.5).
The running YTD columns are computed here on the server precisely because the
SPA must not do arithmetic on money: a client-side running total would add
decimal strings in JavaScript, which is exactly the float drift §5.5 exists
to prevent.

The rows are the same ledger the tax artifacts read — finalized runs and their
stored computations, never a re-derivation — so the year view, the Schedule H
worksheet, and the CSV all agree by construction.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field

from pappy.calc.payroll import EmployeeWithholding, EmployerAccruals
from pappy.decimals import StrictDecimal
from pappy.money import Money


class YearViewRow(BaseModel):
    """One finalized pay run, with the year's running totals through it.

    The gross breakdown is the §5.4 overtime-premium split — straight-time pay
    and the 0.5x premium as separate lines, alongside any extra pay — so an
    overtime question can be answered from the archive without recomputing
    anything. `ytd_*` are running totals including this run, not the run's own
    amounts.
    """

    run_id: str
    pay_date: date
    period_start: date
    period_end: date
    employee_id: str
    employee_name: str

    regular_hours: StrictDecimal
    overtime_hours: StrictDecimal
    other_paid_hours: StrictDecimal
    unpaid_hours: StrictDecimal
    straight_time_pay: Money
    overtime_premium_pay: Money
    extra_pay: Money
    gross: Money

    withholding: EmployeeWithholding
    total_withholding: Money
    net_pay: Money
    employer_accruals: EmployerAccruals

    ytd_gross: Money
    ytd_total_withholding: Money
    ytd_net_pay: Money


class YearViewTotals(BaseModel):
    """Column totals for the year, equal to the last row's running totals.

    Held as its own object rather than being recomputed by the client: the
    CSV's total row and this figure come from the same accumulator pass, so
    they cannot disagree.
    """

    finalized_run_count: int = 0
    gross: Money = Money.zero
    total_withholding: Money = Money.zero
    net_pay: Money = Money.zero
    ytd_gross: Money = Money.zero
    ytd_total_withholding: Money = Money.zero
    ytd_net_pay: Money = Money.zero


class YearView(BaseModel):
    """The §6.2 year view: finalized runs, filterable by date range.

    `period_start`/`period_end` echo the applied range so the CSV and the
    on-screen table describe the same window, and so a stored export can say
    what it covered.
    """

    tax_year: int
    period_start: date | None = None
    period_end: date | None = None
    employee_id: str | None = None
    rows: list[YearViewRow] = Field(default_factory=list)
    totals: YearViewTotals = Field(default_factory=YearViewTotals)
