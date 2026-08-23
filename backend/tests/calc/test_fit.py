"""Golden fixtures for the 2026 Pub. 15-T percentage-method engine.

Every expected value below is hand-derived, step by step, from the 2026
Publication 15-T annual tables transcribed in rates/2026.json — the same
arithmetic Worksheet 1A prescribes. If the engine drifts from these
expectations, CI fails (design-doc.md §5.2).
"""

from datetime import date
from decimal import Decimal

import pytest

from pappy.calc.fit import MissingW4Error, compute_fit, resolve_w4
from pappy.models.common import FilingStatus
from pappy.models.ratetable import RateTable
from pappy.models.w4 import W4Election
from pappy.money import Money


def _w4(
    filing_status: FilingStatus = FilingStatus.SINGLE_OR_MFS,
    *,
    step2c: bool = False,
    credit: Decimal | str = "0",
    other_income: Decimal | str = "0",
    deductions: Decimal | str = "0",
    extra: Decimal | str = "0",
) -> W4Election:
    return W4Election(
        effective_date=date(2026, 1, 1),
        filing_status=filing_status,
        multiple_jobs_step2c=step2c,
        dependent_credit_amount=Decimal(credit),
        other_income=Decimal(other_income),
        deductions=Decimal(deductions),
        extra_withholding=Decimal(extra),
    )


@pytest.mark.parametrize(
    ("filing_status", "step2c", "expected"),
    [
        # $800 weekly → annualized 41,600.
    pytest.param(
        FilingStatus.SINGLE_OR_MFS,
        False,
        "54.08",
        id="single-standard",
        # AAW 41,600-8,600=33,000; single standard 12% bracket (base 1,240
        # at 19,900): 1240+0.12*(33,000-19,900)=2,812; /52=54.076...→54.08
    ),
    pytest.param(
        FilingStatus.MARRIED_JOINTLY,
        False,
        "18.08",
        id="mfj-standard",
        # AAW 41,600-12,900=28,700; 10% over 19,300: 940; /52=18.076...
    ),
    pytest.param(
        FilingStatus.HEAD_OF_HOUSEHOLD,
        False,
        "33.56",
        id="hoh-standard",
        # AAW 33,000; still in the 10% bracket (ends 33,250):
        # 0.10*(33,000-15,550)=1,745; /52=33.557...
    ),
        pytest.param(
            FilingStatus.SINGLE_OR_MFS,
            True,
            "91.10",
            id="single-step2c",
            # Checkbox: no offset; AAW 41,600; 22% over 33,250:
            # 2900+0.22*8,350=4,737; /52=91.096...
        ),
    ],
)
def test_golden_weekly_800(
    rates_2026: RateTable,
    filing_status: FilingStatus,
    step2c: bool,
    expected: str,
) -> None:
    fit = compute_fit(
        period_gross=Money("800.00"),
        w4=_w4(filing_status, step2c=step2c),
        rates=rates_2026,
    )
    assert fit == Money(expected)


def test_golden_exact_threshold_hits_published_base_tax(rates_2026: RateTable) -> None:
    # Single standard: 52,000 annualized + 4(a) 14,500 - 8,600 = 57,900,
    # the exact boundary where the published base tax is 5,800.00.
    fit = compute_fit(
        period_gross=Money("1000.00"),
        w4=_w4(other_income="14500"),
        rates=rates_2026,
    )
    assert fit == Money("111.54")  # 5800/52 = 111.538...


def test_golden_step4b_deductions_shrink_wage(rates_2026: RateTable) -> None:
    # Single standard, $800/wk with 4(b) deductions of 10,400:
    # 1h = 10,400+8,600 = 19,000; AAW = 41,600-19,000 = 22,600;
    # 1240+0.12*2,700 = 1,564; /52 = 30.076... → 30.08.
    fit = compute_fit(period_gross=Money("800.00"), w4=_w4(deductions="10400"), rates=rates_2026)
    assert fit == Money("30.08")


def test_golden_step3_credit_reduces_per_period(rates_2026: RateTable) -> None:
    # Base single-standard on $800 is 54.076...; Step 3 credit 2,200
    # subtracts 42.307... per period → 11.769... → 11.77.
    fit = compute_fit(period_gross=Money("800.00"), w4=_w4(credit="2200"), rates=rates_2026)
    assert fit == Money("11.77")


def test_credit_floors_at_zero_extra_still_applies(rates_2026: RateTable) -> None:
    # Credit 5,200 = 100/period exceeds tentative 54.08 → floors at zero;
    # Step 4(c) adds its flat 25 on top.
    fit = compute_fit(
        period_gross=Money("800.00"),
        w4=_w4(credit="5200", extra="25"),
        rates=rates_2026,
    )
    assert fit == Money("25.00")


def test_zero_gross_withholds_nothing_but_honors_extra(
    rates_2026: RateTable,
) -> None:
    assert compute_fit(period_gross=Money(0), w4=_w4(), rates=rates_2026) == Money(0)


def test_missing_w4_blocks_computation(rates_2026: RateTable) -> None:
    with pytest.raises(MissingW4Error):
        compute_fit(period_gross=Money("800.00"), w4=None, rates=rates_2026)


class TestResolveW4:
    def test_latest_effective_election_wins(self) -> None:
        jan = _w4()
        jul = W4Election(effective_date=date(2026, 7, 1), multiple_jobs_step2c=True)
        assert resolve_w4([jan, jul], pay_date=date(2026, 6, 12)) is jan
        assert resolve_w4([jan, jul], pay_date=date(2026, 7, 3)) is jul

    def test_none_in_effect_raises(self) -> None:
        later = _w4()
        with pytest.raises(MissingW4Error):
            resolve_w4([later], pay_date=date(2025, 12, 31))

    def test_mid_year_change_does_not_touch_earlier_runs(self) -> None:
        original = _w4(extra="50")
        reelected = W4Election(effective_date=date(2026, 7, 1), extra_withholding=Decimal(0))
        resolved = resolve_w4([original, reelected], pay_date=date(2026, 3, 20))
        assert resolved.extra_withholding == Decimal(50)
