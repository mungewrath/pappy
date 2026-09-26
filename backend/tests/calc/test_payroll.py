"""Payroll engine tests (design-doc.md §5.1): withholding lines, net pay,
employer accruals, wage-base caps, and exemption flags.

The full-week golden case is hand-computed line by line from the shipped
2026 rate table; the cap cases exercise every remaining-wage path.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from pappy.calc.fit import MissingW4Error
from pappy.calc.payroll import PayrollResult, YtdContext, compute_payroll
from pappy.models.common import FilingStatus
from pappy.models.ratetable import RateTable
from pappy.models.w4 import W4Election
from pappy.money import Money


def _w4(**overrides: Any) -> W4Election:
    defaults: dict[str, Any] = {
        "effective_date": date(2026, 1, 1),
        "filing_status": FilingStatus.SINGLE_OR_MFS,
    }
    return W4Election.model_validate({**defaults, **overrides})


def _compute(
    rates: RateTable,
    gross: str,
    *,
    w4: W4Election | None = None,
    ytd: YtdContext | None = None,
    ui_rate: str = "0.0122",
    **flags: bool,
) -> PayrollResult:
    return compute_payroll(
        gross=Money(gross),
        w4=w4 if w4 is not None else _w4(),
        rates=rates,
        ytd=ytd,
        wa_ui_experience_rate=Decimal(ui_rate),
        **flags,
    )


class TestFullWeekGolden:
    def test_every_line_of_a_typical_800_week(self, rates_2026: RateTable) -> None:
        result = _compute(rates_2026, "800.00")
        w = result.withholding
        assert w.social_security == Money("49.60")  # 800 * .062
        assert w.medicare == Money("11.60")  # 800 * .0145
        assert w.additional_medicare == Money(0)
        assert w.federal_income_tax == Money("54.08")  # golden case in test_fit.py
        assert w.wa_pfml_employee == Money("6.46")  # 800 * .0113 * .7143
        assert w.wa_cares_employee == Money("4.64")  # 800 * .0058
        assert w.total == Money("126.38")
        assert result.net_pay == Money("673.62")

    def test_employer_accruals_small_employer_default(self, rates_2026: RateTable) -> None:
        accruals = _compute(rates_2026, "800.00").employer_accruals
        assert accruals.social_security == Money("49.60")
        assert accruals.medicare == Money("11.60")
        assert accruals.futa == Money("4.80")  # 800 * (.06 - .054)
        assert accruals.wa_ui == Money("9.76")  # 800 * .0122
        # Fewer than 50 employees: no PFML employer share.
        assert accruals.wa_pfml_employer == Money(0)
        assert accruals.total == Money("75.76")

    def test_pfml_employer_share_when_not_exempt(self, rates_2026: RateTable) -> None:
        result = _compute(rates_2026, "800.00", pfml_small_employer_exempt=False)
        # 800 * .0113 * .2857 = 2.5827...
        assert result.employer_accruals.wa_pfml_employer == Money("2.58")

    def test_wa_cares_exemption_flag(self, rates_2026: RateTable) -> None:
        result = _compute(rates_2026, "800.00", wa_cares_exempt=True)
        assert result.withholding.wa_cares_employee == Money(0)

    def test_missing_w4_blocks_computation(self, rates_2026: RateTable) -> None:
        with pytest.raises(MissingW4Error):
            compute_payroll(
                gross=Money("800.00"),
                w4=None,  # type: ignore[arg-type]
                rates=rates_2026,
            )


class TestExtraPayGolden:
    """A flat lump sum is ordinary taxable wages — same engine, no special case.

    The $25/h, 45-hour week is the $1,187.50 case from
    `tests/services/test_payrun_service.py`; the bonus run adds a flat $250,
    taking gross to $1,437.50. Every line is hand-derived from the 2026 table.
    """

    def test_two_hundred_fifty_bonus_on_a_normal_week(self, rates_2026: RateTable) -> None:
        plain = _compute(rates_2026, "1187.50")
        with_bonus = _compute(rates_2026, "1437.50")

        # The bonus is fully FICA- and Washington-taxable...
        assert with_bonus.withholding.social_security - plain.withholding.social_security == Money(
            "15.50"
        )  # 250 * .062
        assert with_bonus.withholding.medicare - plain.withholding.medicare == Money(
            "3.62"
        )  # 250 * .0145 = 3.625, quantized against the larger base
        assert (
            with_bonus.withholding.wa_pfml_employee - plain.withholding.wa_pfml_employee
            == Money("2.01")  # 250 * .0113 * .7143
        )
        assert (
            with_bonus.withholding.wa_cares_employee - plain.withholding.wa_cares_employee
            == Money("1.45")  # 250 * .0058
        )

        # ...and the whole payment is annualized as one periodic wage
        # (Pub. 15 §7, supplemental wages combined with regular wages).
        # $1,437.50 x 52 = $74,750 less the $8,600 offset = $66,150, which
        # crosses into the 22% bracket: $5,800 + 8,250 x .22 = $7,615/yr.
        assert plain.withholding.federal_income_tax == Money("100.58")
        assert with_bonus.withholding.federal_income_tax == Money("146.44")
        # $45.86 on $250 is 18.3% — below Pub. 15 §7 method 1a's flat 22%,
        # because annualizing a small bonus across 52 periods smooths it.
        assert with_bonus.withholding.federal_income_tax - plain.withholding.federal_income_tax == (
            Money("45.86")
        )

        # employer side follows the same base (FUTA has $7,000 of room at zero YTD)
        assert with_bonus.employer_accruals.social_security == Money("89.13")
        assert with_bonus.employer_accruals.medicare == Money("20.84")
        assert with_bonus.employer_accruals.futa == Money("8.63")  # 1437.50 * .006

    def test_bonus_never_raises_a_negative_net(self, rates_2026: RateTable) -> None:
        result = _compute(rates_2026, "250.00")
        assert result.gross == Money("250.00")
        assert result.net_pay > Money(0)
        assert result.net_pay == result.gross - result.withholding.total


class TestWageBaseCaps:
    def test_social_security_cap_partial_then_full(self, rates_2026: RateTable) -> None:
        near_cap = YtdContext(
            social_security_wages=Decimal(184400), wa_pfml_wages=Decimal(184400)
        )
        result = _compute(rates_2026, "800.00", ytd=near_cap)
        assert result.taxable.social_security == Decimal(100)
        assert result.withholding.social_security == Money("6.20")
        over_cap = YtdContext(
            social_security_wages=Decimal(185000),
            medicare_wages=Decimal(185000),
            wa_pfml_wages=Decimal(185000),
        )
        result = _compute(rates_2026, "800.00", ytd=over_cap)
        assert result.withholding.social_security == Money(0)
        # Medicare itself has no cap.
        assert result.withholding.medicare == Money("11.60")

    def test_additional_medicare_kicks_in_above_threshold(
        self, rates_2026: RateTable
    ) -> None:
        near = YtdContext(medicare_wages=Decimal(199900))
        result = _compute(rates_2026, "800.00", ytd=near)
        assert result.taxable.additional_medicare == Decimal(700)
        assert result.withholding.additional_medicare == Money("6.30")  # 700 * .009
        past = YtdContext(medicare_wages=Decimal(200000))
        result = _compute(rates_2026, "800.00", ytd=past)
        assert result.withholding.additional_medicare == Money("7.20")  # 800 * .009

    def test_futa_stops_at_seven_thousand(self, rates_2026: RateTable) -> None:
        result = _compute(rates_2026, "800.00", ytd=YtdContext(futa_wages=Decimal(6500)))
        assert result.taxable.futa == Decimal(500)
        assert result.employer_accruals.futa == Money("3.00")
        done = _compute(rates_2026, "800.00", ytd=YtdContext(futa_wages=Decimal(7000)))
        assert done.employer_accruals.futa == Money(0)

    def test_wa_ui_cap_and_experience_rate(self, rates_2026: RateTable) -> None:
        result = _compute(
            rates_2026, "800.00", ytd=YtdContext(wa_ui_wages=Decimal(78000))
        )
        assert result.taxable.wa_ui == Decimal(200)
        assert result.employer_accruals.wa_ui == Money("2.44")
        done = _compute(
            rates_2026,
            "800.00",
            ytd=YtdContext(wa_ui_wages=Decimal(78200)),
            ui_rate="0.0515",
        )
        assert done.employer_accruals.wa_ui == Money(0)


class TestInvariants:
    @pytest.mark.parametrize(
        ("gross", "ytd"),
        [
            ("0.00", None),
            ("25.37", None),
            ("800.00", None),
            ("1845.90", YtdContext(social_security_wages=Decimal(184000))),
            ("3000.00", YtdContext(medicare_wages=Decimal(199500))),
        ],
    )
    def test_net_is_gross_minus_withholding(
        self,
        rates_2026: RateTable,
        gross: str,
        ytd: YtdContext | None,
    ) -> None:
        result = _compute(rates_2026, gross, ytd=ytd)
        assert result.net_pay == result.gross - result.withholding.total

    def test_no_line_is_negative(self, rates_2026: RateTable) -> None:
        result = _compute(rates_2026, "12.50", ytd=YtdContext())
        for line in (
            result.withholding.social_security,
            result.withholding.medicare,
            result.withholding.additional_medicare,
            result.withholding.federal_income_tax,
            result.withholding.wa_pfml_employee,
            result.withholding.wa_cares_employee,
            result.net_pay,
        ):
            assert line >= Money(0)
