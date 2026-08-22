"""Shared object factories for tests.

Kept deliberately small: only helpers needed by more than one test module.
"""

from __future__ import annotations

from datetime import date

from pappy.calc.payroll import PayrollResult, YtdContext, compute_payroll
from pappy.models.ratetable import RateTable
from pappy.models.w4 import W4Election
from pappy.money import Money


def make_w4(effective_date: date = date(2026, 1, 1)) -> W4Election:
    """A single-filer, no-adjustments W-4 — the common nanny case."""
    return W4Election(effective_date=effective_date)


def make_payroll(
    gross: str,
    rates: RateTable,
    *,
    w4: W4Election | None = None,
    ytd: YtdContext | None = None,
) -> PayrollResult:
    """Compute a realistic `PayrollResult` for a given gross."""
    return compute_payroll(
        gross=Money(gross),
        w4=w4 if w4 is not None else make_w4(),
        rates=rates,
        ytd=ytd,
    )
