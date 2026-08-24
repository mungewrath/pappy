"""Tax-year aggregation over finalized runs (design-doc.md §5.3, §6.4-§6.6).

Pure calculation, no AWS imports. The service layer reduces each finalized
run to a `RunContribution` (its year-artifact lines); this module folds
those into quarterly 1040-ES figures and full-year totals.

Quarters follow the calendar and runs are attributed by *pay date* (cash
basis): the money became owed when the paycheck was cut, which is how the
IRS expects estimated payments to track liability.

Import discipline: `pappy.models.payrun` imports this package's siblings,
so calc must not import it back — hence the light-weight `RunContribution`
input instead of the full PayRun model.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel

from pappy.decimals import StrictDecimal
from pappy.money import Money


class RunContribution(BaseModel):
    """One finalized pay run reduced to its year-artifact lines.

    Social Security and Medicare arrive split so Schedule H can show the
    statutory combined rates while 1040-ES sums both halves; `futa` is the
    employer's accrual only. The wage slices are the *taxable* amounts
    after the year's wage-base caps were applied at finalization (§5.1),
    stored on the run — full-precision Decimals like all covered-wage
    quantities (§ models/ytd).
    """

    run_id: str
    employee_id: str
    pay_date: date
    gross: Money
    federal_income_tax_withheld: Money = Money.zero
    ee_social_security: Money = Money.zero
    er_social_security: Money = Money.zero
    ee_medicare: Money = Money.zero
    er_medicare: Money = Money.zero
    additional_medicare: Money = Money.zero
    futa: Money = Money.zero
    wa_pfml_employee: Money = Money.zero  # W-2 Box 14 (informational)
    wa_cares_employee: Money = Money.zero  # W-2 Box 14 (informational)
    ss_wages: StrictDecimal = Decimal(0)
    additional_medicare_wages: StrictDecimal = Decimal(0)

    @property
    def social_security(self) -> Money:
        """Both halves — Schedule H line B is 12.4% of line A."""
        return self.ee_social_security + self.er_social_security

    @property
    def medicare(self) -> Money:
        """Both halves — Schedule H line D is 2.9% of line C."""
        return self.ee_medicare + self.er_medicare

    @property
    def household_employment_taxes(self) -> Money:
        """The Schedule H line J analog for this run alone."""
        return Money.sum(
            [
                self.federal_income_tax_withheld,
                self.social_security,
                self.medicare,
                self.additional_medicare,
            ]
        )


class TaxTotals(BaseModel):
    """Folded contribution totals for any scope (one quarter or a year)."""

    pay_run_count: int = 0
    gross: Money = Money.zero
    federal_income_tax_withheld: Money = Money.zero
    social_security: Money = Money.zero
    medicare: Money = Money.zero
    additional_medicare: Money = Money.zero
    futa: Money = Money.zero
    ss_wages: StrictDecimal = Decimal(0)
    additional_medicare_wages: StrictDecimal = Decimal(0)

    @property
    def household_employment_taxes(self) -> Money:
        return Money.sum(
            [
                self.federal_income_tax_withheld,
                self.social_security,
                self.medicare,
                self.additional_medicare,
            ]
        )

    @property
    def total(self) -> Money:
        """Household employment taxes plus FUTA — the 1040-ES figure."""
        return self.household_employment_taxes + self.futa

    def apply(self, contribution: RunContribution) -> None:
        self.pay_run_count += 1
        self.gross = self.gross + contribution.gross
        self.federal_income_tax_withheld = (
            self.federal_income_tax_withheld + contribution.federal_income_tax_withheld
        )
        self.social_security = self.social_security + contribution.social_security
        self.medicare = self.medicare + contribution.medicare
        self.additional_medicare = self.additional_medicare + contribution.additional_medicare
        self.futa = self.futa + contribution.futa
        self.ss_wages += contribution.ss_wages
        self.additional_medicare_wages += contribution.additional_medicare_wages

    @classmethod
    def fold(cls, contributions: list[RunContribution]) -> TaxTotals:
        totals = cls()
        for contribution in contributions:
            totals.apply(contribution)
        return totals


class QuarterTotals(BaseModel):
    """One calendar quarter's totals plus the cumulative amount through it."""

    quarter: int
    totals: TaxTotals
    ytd_total: Money


_QUARTER_BOUNDS: dict[int, tuple[tuple[int, int], tuple[int, int]]] = {
    1: ((1, 1), (3, 31)),
    2: ((4, 1), (6, 30)),
    3: ((7, 1), (9, 30)),
    4: ((10, 1), (12, 31)),
}

# Form 1040-ES payment due dates for a calendar-tax-year individual.
# Calendar-day anchors only — the IRS slides weekends/holidays (and Q1's
# Apr 15 can move for Emancipation Day); verify against the current-year
# 1040-ES instructions before scheduling a payment (§5.2 ethos: data and
# dates like these are verified, never assumed).
_QUARTER_DUE: dict[int, tuple[int, int]] = {
    1: (4, 15),
    2: (6, 15),
    3: (9, 15),
}


def quarter_of(pay_date: date) -> int:
    return (pay_date.month - 1) // 3 + 1


def quarter_bounds(tax_year: int, quarter: int) -> tuple[date, date]:
    (start_month, start_day), (end_month, end_day) = _QUARTER_BOUNDS[quarter]
    return (
        date(tax_year, start_month, start_day),
        date(tax_year, end_month, end_day),
    )


def estimate_due_date(tax_year: int, quarter: int) -> date:
    if quarter == 4:
        return date(tax_year + 1, 1, 15)
    month, day = _QUARTER_DUE[quarter]
    return date(tax_year, month, day)


def sort_chronologically(contributions: list[RunContribution]) -> list[RunContribution]:
    return sorted(contributions, key=lambda c: (c.pay_date, c.run_id))


def aggregate_quarterly(
    contributions: list[RunContribution], *, tax_year: int
) -> list[QuarterTotals]:
    """Four rows, always — quiet quarters stay visible at zero so the
    year's payment plan reads as a whole."""
    buckets: dict[int, list[RunContribution]] = {q: [] for q in range(1, 5)}
    for contribution in contributions:
        if contribution.pay_date.year != tax_year:
            continue
        buckets[quarter_of(contribution.pay_date)].append(contribution)

    results: list[QuarterTotals] = []
    running = Money(0)
    for quarter in range(1, 5):
        totals = TaxTotals.fold(buckets[quarter])
        running = running + totals.total
        results.append(QuarterTotals(quarter=quarter, totals=totals, ytd_total=running))
    return results


def aggregate_year(contributions: list[RunContribution]) -> TaxTotals:
    return TaxTotals.fold(contributions)
