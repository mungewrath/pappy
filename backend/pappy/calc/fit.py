"""Federal income tax withholding — Pub. 15-T percentage method.

Implements design-doc.md §5.3 ("Percentage method, annualized") via the
2026 Publication 15-T Worksheet 1A for automated payroll systems: the
pay-period wage is annualized at 52 periods, adjusted for the W-4's
Step 2(c)/3/4 elections, run through the filing-status rate schedule,
credited on an annualized basis, divided back down to the period, and
topped up with Step 4(c).

Floor-at-zero rules follow the publication exactly: neither the adjusted
annual wage (line 1i), nor the tentative amount after the Step 3 credit
(line 3c), nor the final result may go negative. Money is quantized once,
half-up at the cent, on the final per-period amount only.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pappy.decimals import StrictDecimal
from pappy.models.ratetable import FederalTaxBracket, RateTable
from pappy.models.w4 import W4Election
from pappy.money import Money


class MissingW4Error(ValueError):
    """Raised when a pay run is computed without a W-4 election (§5.3).

    A household employer withholds federal income tax only by mutual
    agreement; once that agreement exists the W-4 is required input and a
    missing election must block computation rather than silently default.
    """


def compute_fit(*, period_gross: Money, w4: W4Election | None, rates: RateTable) -> Money:
    """Withhold for one period under Worksheet 1A.

    Raises `MissingW4Error` when `w4` is None — a missing election blocks
    computation rather than silently defaulting (§5.3).
    """
    if w4 is None:
        raise MissingW4Error("a W-4 election is required to compute federal withholding")
    periods = Decimal(rates.pay_periods_per_year)

    # Line 1c: annualize. Line 1e: add Step 4(a).
    annualized = period_gross.amount * periods
    line_1e = annualized + w4.other_income

    # Lines 1f/1g/1h/1i: subtract Step 4(b) plus the schedule offset
    # ($12,900 MFJ / $8,600 otherwise on standard schedules; zero when the
    # Step 2 checkbox is checked), floored at zero.
    if w4.multiple_jobs_step2c:
        offset = Decimal(0)
    else:
        offset = rates.fit_standard_offsets[w4.filing_status]
    line_1h = w4.deductions + offset
    adjusted_annual_wage = max(Decimal(0), line_1e - line_1h)

    brackets = rates.federal_income_tax.table_for(
        filing_status=w4.filing_status, step2c_checked=w4.multiple_jobs_step2c
    )
    annual_tax = _bracket_tax(brackets, adjusted_annual_wage)

    # Lines 2h/3b/3c: divide to the period, then subtract the Step 3
    # credit on an annualized basis — never below zero.
    tentative_per_period = annual_tax / periods
    credit_per_period = w4.dependent_credit_amount / periods
    after_credit = max(Decimal(0), tentative_per_period - credit_per_period)

    # Line 4b: add Step 4(c) extra per-period withholding.
    return Money(after_credit + w4.extra_withholding)


def _bracket_tax(brackets: list[FederalTaxBracket], wage: StrictDecimal) -> Decimal:
    """Tentative annual withholding for an adjusted annual wage (lines 2a-2g)."""
    applicable: FederalTaxBracket | None = None
    for bracket in brackets:
        if wage < bracket.threshold:
            break
        applicable = bracket
    if applicable is None:
        # Unreachable for any validated rate table: every schedule starts at 0.
        raise ValueError(f"no bracket matches wage {wage}")
    excess = wage - applicable.threshold
    return applicable.base_tax + excess * applicable.marginal_rate


def resolve_w4(elections: list[W4Election], *, pay_date: date) -> W4Election:
    """Pick the election in effect on a pay date (§5.3 mid-year changes).

    Elections take effect on their `effective_date`; the latest one dated
    on or before the pay date wins. Raises `MissingW4Error` when no
    election is in effect yet.
    """
    effective = sorted(
        (e for e in elections if e.effective_date <= pay_date),
        key=lambda e: e.effective_date,
    )
    if not effective:
        raise MissingW4Error(f"no W-4 election in effect on {pay_date}")
    return effective[-1]
