"""Gross pay calculation — pure, no AWS, no I/O.

Implements design-doc.md §5.1 step 1 ("Gross = Σ(hours × applicable rate).
Overtime at 1.5× for hours over 40 in a workweek ... configurable per
employee with a default of 'overtime applies'") and the §5.4 overtime-premium
breakdown ("shown as two explicit lines rather than one blended figure —
straight-time hours at the base rate, and the 0.5× premium on overtime hours
as its own line").

Withholding, net pay, and employer tax accruals (§5.1 steps 2-4) are
computed by `pappy.calc.payroll`, built on `pappy.calc.fit` (the Pub.
15-T percentage-method engine) and versioned rate tables (§5.2).

**Overtime detection.** A pay run's hour lines cover one workweek. Hours
categorized `REGULAR` count toward the 40-hour weekly threshold; any excess
is automatically paid at the 0.5x premium in addition to the base rate.
Hours the employer has explicitly categorized `OVERTIME` (e.g. a
pre-designated overtime shift) are always paid at the premium rate,
regardless of the 40-hour threshold. `PTO`, `HOLIDAY`, and `SICK` hours are
paid at the base rate but do not count toward the overtime threshold.
`UNPAID` hours contribute nothing to gross.

If the employee's `overtime_policy` is `EXEMPT` (design-doc.md §5.1 —
live-in employees are FLSA-exempt from overtime), no premium is ever
applied; all paid hours are straight time.

**Extra pay.** A run may also carry flat extra pay lines — a bonus, gift, or
similar — entered as a direct cent amount with a note for the stub rather than
derived from hours. They are added to gross as a third explicit line, and are
taxable wages like any other (§ models.payrun.ExtraPayLine).
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel

from pappy.decimals import StrictDecimal
from pappy.models.common import HourCategory, OvertimePolicy
from pappy.money import Money

if TYPE_CHECKING:
    from pappy.models.payrun import ExtraPayLine, HourLine

REGULAR_WEEKLY_THRESHOLD = Decimal(40)
OVERTIME_PREMIUM_MULTIPLIER = Decimal("0.5")

_PAID_CATEGORIES = frozenset(
    {
        HourCategory.REGULAR,
        HourCategory.OVERTIME,
        HourCategory.PTO,
        HourCategory.HOLIDAY,
        HourCategory.SICK,
    }
)


class GrossPayResult(BaseModel):
    """Gross pay for one pay run, with the overtime premium and any extra pay
    broken out.

    `straight_time_pay` covers *all* paid hours (regular, overtime,
    PTO/holiday/sick) at the base rate; `overtime_premium_pay` is only the
    additional 0.5x on overtime hours. `extra_pay` is the sum of the run's
    flat extra pay lines (bonuses and the like) — hours-independent by
    definition. `gross` is the total of all three. This mirrors the pay-stub
    line breakdown required by design-doc.md §5.4.
    """

    regular_hours: StrictDecimal
    overtime_hours: StrictDecimal
    other_paid_hours: StrictDecimal
    unpaid_hours: StrictDecimal
    hourly_rate: StrictDecimal
    straight_time_pay: Money
    overtime_premium_pay: Money
    # `GrossPayResult` is persisted inside the `PayRun` item, so a stored run
    # written before extra pay existed has no `extra_pay` key at all. It had none
    # by definition, so zero is the correct backfill rather than a guess — and
    # reading those runs must not fail (see `repo.payrun_repo._from_item`).
    extra_pay: Money = Money.zero
    gross: Money

    @property
    def effective_overtime_rate(self) -> Decimal | None:
        if self.overtime_hours <= 0:
            return None
        return self.hourly_rate * (Decimal(1) + OVERTIME_PREMIUM_MULTIPLIER)


def compute_gross_pay(
    *,
    hour_lines: list[HourLine],
    hourly_rate: Decimal,
    overtime_policy: OvertimePolicy,
    extra_pay_lines: list[ExtraPayLine] | None = None,
) -> GrossPayResult:
    regular_hours = Decimal(0)
    tagged_overtime_hours = Decimal(0)
    other_paid_hours = Decimal(0)
    unpaid_hours = Decimal(0)

    for line in hour_lines:
        if line.category == HourCategory.REGULAR:
            regular_hours += line.hours
        elif line.category == HourCategory.OVERTIME:
            tagged_overtime_hours += line.hours
        elif line.category in _PAID_CATEGORIES:
            other_paid_hours += line.hours
        elif line.category == HourCategory.UNPAID:
            unpaid_hours += line.hours
        else:  # pragma: no cover - exhaustive over HourCategory
            raise ValueError(f"Unknown hour category: {line.category!r}")

    if overtime_policy == OvertimePolicy.EXEMPT:
        # No premium regardless of hours worked; everything is straight time.
        straight_hours = regular_hours + tagged_overtime_hours + other_paid_hours
        overtime_hours = Decimal(0)
    else:
        auto_overtime_hours = max(Decimal(0), regular_hours - REGULAR_WEEKLY_THRESHOLD)
        overtime_hours = auto_overtime_hours + tagged_overtime_hours
        straight_hours = regular_hours + tagged_overtime_hours + other_paid_hours

    straight_time_pay = _pay_for_hours(straight_hours, hourly_rate)
    overtime_premium_pay = _pay_for_hours(overtime_hours * OVERTIME_PREMIUM_MULTIPLIER, hourly_rate)
    # Extra pay is entered as a direct amount, so nothing to derive here. Every
    # line is already a cent-quantized Money, so the sum below is exact and a
    # run with no extra pay reproduces the hours-only gross bit for bit.
    extra_pay = Money.sum([line.amount for line in extra_pay_lines or []])
    gross = straight_time_pay + overtime_premium_pay + extra_pay

    return GrossPayResult(
        regular_hours=regular_hours,
        overtime_hours=overtime_hours,
        other_paid_hours=other_paid_hours,
        unpaid_hours=unpaid_hours,
        hourly_rate=hourly_rate,
        straight_time_pay=straight_time_pay,
        overtime_premium_pay=overtime_premium_pay,
        extra_pay=extra_pay,
        gross=gross,
    )


def _pay_for_hours(hours: Decimal, hourly_rate: Decimal) -> Money:
    """Money for a number of hours at a given rate, quantized once."""
    return Money(hours * hourly_rate)
