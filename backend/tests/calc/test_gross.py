from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pappy.calc.gross import compute_gross_pay
from pappy.models.common import HourCategory, OvertimePolicy
from pappy.models.payrun import ExtraPayLine, HourLine
from pappy.money import Money


def _line(day: int, hours: str, category: HourCategory = HourCategory.REGULAR) -> HourLine:
    return HourLine(work_date=date(2026, 1, day), hours=Decimal(hours), category=category)


def _bonus(amount: str, note: str = "Bonus") -> ExtraPayLine:
    return ExtraPayLine(note=note, amount=Money(amount))


def test_no_overtime_under_40_hours() -> None:
    lines = [_line(d, "8") for d in range(1, 6)]  # 5 x 8 = 40
    result = compute_gross_pay(
        hour_lines=lines, hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.APPLIES
    )
    assert result.regular_hours == Decimal(40)
    assert result.overtime_hours == Decimal(0)
    assert result.straight_time_pay == Money("800.00")
    assert result.overtime_premium_pay == Money("0.00")
    assert result.gross == Money("800.00")


def test_overtime_over_40_hours_applies_premium() -> None:
    lines = [_line(d, "9") for d in range(1, 6)]  # 5 x 9 = 45
    result = compute_gross_pay(
        hour_lines=lines, hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.APPLIES
    )
    assert result.regular_hours == Decimal(45)
    assert result.overtime_hours == Decimal(5)
    # straight time pays all 45 hours at base rate
    assert result.straight_time_pay == Money("900.00")
    # premium is 0.5x on the 5 OT hours: 5 * 0.5 * 20 = 50
    assert result.overtime_premium_pay == Money("50.00")
    assert result.gross == Money("950.00")
    assert result.effective_overtime_rate == Decimal("30.00")


def test_explicit_overtime_category_always_gets_premium() -> None:
    lines = [_line(1, "5", HourCategory.OVERTIME)]
    result = compute_gross_pay(
        hour_lines=lines, hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.APPLIES
    )
    assert result.overtime_hours == Decimal(5)
    assert result.straight_time_pay == Money("100.00")
    assert result.overtime_premium_pay == Money("50.00")
    assert result.gross == Money("150.00")


def test_exempt_employee_never_gets_premium() -> None:
    lines = [_line(d, "10") for d in range(1, 6)]  # 50 hours
    result = compute_gross_pay(
        hour_lines=lines, hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.EXEMPT
    )
    assert result.overtime_hours == Decimal(0)
    assert result.overtime_premium_pay == Money("0.00")
    assert result.gross == Money("1000.00")  # 50 * 20, no premium


def test_pto_and_holiday_paid_but_not_counted_toward_overtime() -> None:
    lines = [
        _line(1, "40"),
        _line(2, "8", HourCategory.PTO),
    ]
    result = compute_gross_pay(
        hour_lines=lines, hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.APPLIES
    )
    assert result.regular_hours == Decimal(40)
    assert result.other_paid_hours == Decimal(8)
    assert result.overtime_hours == Decimal(0)
    assert result.gross == Money("960.00")  # 48 hours * 20, no premium


def test_unpaid_hours_contribute_nothing() -> None:
    lines = [_line(1, "8"), _line(2, "8", HourCategory.UNPAID)]
    result = compute_gross_pay(
        hour_lines=lines, hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.APPLIES
    )
    assert result.unpaid_hours == Decimal(8)
    assert result.gross == Money("160.00")


def test_no_hours_gives_zero_gross() -> None:
    result = compute_gross_pay(
        hour_lines=[], hourly_rate=Decimal("20.00"), overtime_policy=OvertimePolicy.APPLIES
    )
    assert result.gross == Money("0.00")
    assert result.effective_overtime_rate is None


def test_extra_pay_adds_to_gross() -> None:
    lines = [_line(d, "9") for d in range(1, 6)]  # 5 x 9 = 45
    result = compute_gross_pay(
        hour_lines=lines,
        hourly_rate=Decimal("25.00"),
        overtime_policy=OvertimePolicy.APPLIES,
        extra_pay_lines=[_bonus("250.00", "Holiday bonus")],
    )
    # hours are untouched by the flat amount
    assert result.regular_hours == Decimal(45)
    assert result.overtime_hours == Decimal(5)
    assert result.straight_time_pay == Money("1125.00")
    assert result.overtime_premium_pay == Money("62.50")
    # 1125.00 + 62.50 + 250.00
    assert result.extra_pay == Money("250.00")
    assert result.gross == Money("1437.50")


def test_extra_pay_is_independent_of_hours() -> None:
    """A bonus on a zero-hour run is still gross — it is not hours-derived."""
    result = compute_gross_pay(
        hour_lines=[],
        hourly_rate=Decimal("25.00"),
        overtime_policy=OvertimePolicy.APPLIES,
        extra_pay_lines=[_bonus("250.00")],
    )
    assert result.straight_time_pay == Money("0.00")
    assert result.extra_pay == Money("250.00")
    assert result.gross == Money("250.00")


def test_several_extra_pay_lines_sum_into_one_gross_line() -> None:
    result = compute_gross_pay(
        hour_lines=[_line(1, "8")],
        hourly_rate=Decimal("20.00"),
        overtime_policy=OvertimePolicy.APPLIES,
        extra_pay_lines=[_bonus("250.00", "Bonus"), _bonus("100.50", "Referral")],
    )
    assert result.extra_pay == Money("350.50")
    assert result.gross == Money("510.50")  # 160.00 + 350.50


def test_no_extra_pay_lines_reproduce_the_hours_only_gross() -> None:
    lines = [_line(d, "9") for d in range(1, 6)]
    kwargs = {
        "hour_lines": lines,
        "hourly_rate": Decimal("25.00"),
        "overtime_policy": OvertimePolicy.APPLIES,
    }
    with_empty = compute_gross_pay(**kwargs, extra_pay_lines=[])  # type: ignore[arg-type]
    without = compute_gross_pay(**kwargs)  # type: ignore[arg-type]
    assert with_empty.extra_pay == Money("0.00")
    assert with_empty.gross == without.gross == Money("1187.50")


def test_extra_pay_rejected_when_blank_note() -> None:
    with pytest.raises(ValidationError):
        ExtraPayLine(note="   ", amount=Money("250.00"))


def test_extra_pay_rejected_when_amount_negative() -> None:
    with pytest.raises(ValidationError):
        ExtraPayLine(note="Clawback", amount=Money("-1.00"))


def test_extra_pay_rejects_float_amount() -> None:
    with pytest.raises(TypeError):
        ExtraPayLine(note="Bonus", amount=250.5)  # type: ignore[arg-type]
