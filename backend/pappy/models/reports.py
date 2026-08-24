"""Response schemas for tax-year artifacts (design-doc.md §9 Phase 6).

Every money field is a `Money`, serialized as an exact decimal string
(§5.5) — all aggregation happens server-side and the SPA only formats.

The artifacts produced here are the *numbers* behind the paper forms:
quarterly 1040-ES figures, Schedule H line values, W-2 box values, and the
annual earnings summary (§5.4, §6.4-§6.6). Rendering those numbers into the
official PDF AcroForms arrives with the document store; these schemas are
what both the UI and the future generators will consume.
"""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from pappy.calc.payroll import EmployeeWithholding, EmployerAccruals
from pappy.decimals import StrictDecimal
from pappy.models.payrun import PayRun
from pappy.money import Money


class QuarterEstimate(BaseModel):
    """One quarter's 1040-ES contribution (design-doc.md §5.3, §6.6).

    A household employer pays household employment taxes through Form 1040
    estimated payments: withheld federal income tax plus both halves of
    Social Security and Medicare (Schedule H lines B/D/G/I), with FUTA
    (line L) on top of that total. State UI/PFML/Cares obligations are
    deliberately absent — they are not part of 1040-ES.

    Runs are attributed to quarters by *pay date* (cash basis), matching
    when the money left the paycheck and became owed to the IRS.
    """

    quarter: int = Field(ge=1, le=4)
    period_start: date
    period_end: date
    due_date: date
    pay_run_count: int = 0
    gross: Money = Money.zero
    federal_income_tax_withheld: Money = Money.zero
    social_security: Money = Money.zero  # employee + employer halves
    medicare: Money = Money.zero  # employee + employer halves
    additional_medicare: Money = Money.zero
    household_employment_taxes: Money = Money.zero  # Schedule H line J analog
    futa: Money = Money.zero
    total: Money = Money.zero  # line M analog — owed via 1040-ES
    ytd_total: Money = Money.zero  # running total through this quarter


class QuarterlyEstimates(BaseModel):
    """All four quarters of a tax year — always four rows, zero-filled when
    quiet, so the year's payment plan is visible at a glance."""

    tax_year: int
    quarters: list[QuarterEstimate]
    grand_total: Money


class ContributingRun(BaseModel):
    """One finalized run's contribution to a year artifact — the audit trail
    behind each aggregate ("which pay runs contributed to each line",
    design-doc.md §6.4)."""

    run_id: str
    employee_id: str
    employee_name: str | None = None
    pay_date: date
    gross: Money
    social_security: Money  # employee + employer halves
    medicare: Money  # employee + employer halves
    additional_medicare: Money
    federal_income_tax_withheld: Money
    futa: Money


class ScheduleHWorksheet(BaseModel):
    """Schedule H (Form 1040) line values derived from finalized runs.

    Lines B/D/G are the *stored per-run computations* summed — equal to the
    statutory rate × line A/C/F wages up to per-payday rounding, which is
    the IRS's own convention for payroll taxes. Line L (FUTA) accrues only
    on the first $7,000 of wages per employee. The state-unemployment
    questions (lines K/N) are answered by the employer at filing time; they
    are not computed here.
    """

    tax_year: int
    employer_name: str
    employer_ein: str
    line_a_ss_wages: Money
    line_b_ss_tax: Money
    line_c_medicare_wages: Money
    line_d_medicare_tax: Money
    line_e_subtotal: Money
    line_f_addl_medicare_wages: Money
    line_g_addl_medicare_tax: Money
    line_h_household_fica_taxes: Money
    line_i_fit_withheld: Money
    line_j_total_household_employment_taxes: Money
    line_l_futa_tax: Money
    line_m_total: Money
    contributing_runs: list[ContributingRun]


class W2Box14Item(BaseModel):
    """An informational Box 14 entry — Washington has no state income tax,
    so PFML and WA Cares employee contributions land here."""

    label: str
    amount: Money


class W2Summary(BaseModel):
    """W-2 box values for one employee's tax year.

    Box 1 equals total cash wages: household employees have no pre-tax
    benefit deductions in scope, so everything is taxable federal wages.
    The employee's SSN is deliberately absent (design-doc.md §7.3 — never
    stored client-side or returned to the browser); it is supplied
    transiently only when the EFW2 file is generated.
    """

    tax_year: int
    employer_name: str
    employer_ein: str
    employee_id: str
    employee_name: str
    box1_wages: Money
    box2_fit_withheld: Money
    box3_ss_wages: Money
    box4_ss_tax_withheld: Money
    box5_medicare_wages: Money
    box6_medicare_tax_withheld: Money
    box14_items: list[W2Box14Item]


class WageBaseUsage(BaseModel):
    """How much of one wage-base cap the year has consumed (§4 accumulators).

    Amounts are `StrictDecimal` rather than `Money` — these are internal
    covered-wage quantities (§ models/ytd), shown for planning, not pay.
    """

    name: str
    label: str
    wages_used: StrictDecimal
    wage_base: StrictDecimal | None = None  # None = uncapped
    remaining: StrictDecimal | None = None  # None when uncapped


class QuarterGross(BaseModel):
    """Per-quarter gross for the earnings summary's quarter columns."""

    quarter: int
    gross: Money
    ytd_gross: Money


class EarningsSummary(BaseModel):
    """Annual earnings summary for one employee (§5.4, §6.6).

    Carries the overtime-premium breakdown required of the year view, every
    withholding line as a year total with YTD semantics, employer accruals,
    quarterly gross progression, and wage-base consumption.
    """

    tax_year: int
    employee_id: str
    employee_name: str
    hourly_rate: StrictDecimal
    finalized_run_count: int
    hours_regular: StrictDecimal
    hours_overtime: StrictDecimal
    hours_other_paid: StrictDecimal
    hours_unpaid: StrictDecimal
    straight_time_pay: Money
    overtime_premium_pay: Money
    gross: Money
    withholding: EmployeeWithholding
    net_pay: Money
    employer_accruals: EmployerAccruals
    quarterly_gross: list[QuarterGross]
    wage_bases: list[WageBaseUsage]


class BackfillMode(str, Enum):
    """How backfilled weeks get their hour lines.

    SCHEDULE seeds each week from the employee's default weekly schedule
    (§6.1); FLAT spreads a fixed weekly total evenly across that schedule's
    workdays instead.
    """

    SCHEDULE = "SCHEDULE"
    FLAT = "FLAT"


class BackfillCreate(BaseModel):
    """Request to create weekly DRAFT runs over a historical date range.

    Weeks are Monday-starting periods of up to seven days from
    `period_start`, paid on the next `pay_weekday` after each period ends.
    Existing runs are never touched — overlapping weeks are skipped, not
    overwritten.
    """

    period_start: date
    period_end: date
    pay_weekday: int = Field(default=4, ge=0, le=6)  # 4 = Friday
    mode: BackfillMode = BackfillMode.SCHEDULE
    weekly_hours: StrictDecimal | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> BackfillCreate:
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        span_days = (self.period_end - self.period_start).days + 1
        if span_days > 366:
            raise ValueError(
                "backfill range spans more than 366 days; split it into smaller ranges"
            )
        if self.mode == BackfillMode.FLAT and (self.weekly_hours is None or self.weekly_hours <= 0):
            raise ValueError("weekly_hours is required and must be positive for FLAT mode")
        return self


class SkippedWeek(BaseModel):
    """A week the backfill did not create, and why."""

    period_start: date
    period_end: date
    reason: str


class BackfillResult(BaseModel):
    created: list[PayRun]
    skipped: list[SkippedWeek]


class FinalizeFailure(BaseModel):
    run_id: str
    pay_date: date
    detail: str


class FinalizePendingResult(BaseModel):
    """Outcome of a chronological bulk finalization: the run IDs locked and
    the drafts that could not be finalized, each with its reason (missing
    W-4, missing rate table, out-of-order pay date, ...)."""

    finalized: list[str]
    failed: list[FinalizeFailure]
