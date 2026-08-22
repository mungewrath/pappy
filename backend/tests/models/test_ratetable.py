"""Rate-table loading and validation tests (design-doc.md §5.2).

A malformed rate must fail at load, never at payroll time; these tests
feed deliberately broken JSON through `parse_rate_table` to prove it.
"""

import copy
import itertools
from decimal import Decimal

import pytest
from pydantic import ValidationError

from pappy.models.common import FilingStatus
from pappy.models.ratetable import RateTable, parse_rate_table


def test_loads_shipped_2026_table(rates_2026: RateTable) -> None:
    assert rates_2026.tax_year == 2026
    assert rates_2026.version == 1
    assert rates_2026.rate_table_id == "2026#v1"
    assert rates_2026.pay_periods_per_year == 52
    assert rates_2026.futa.effective_rate == Decimal("0.006")
    assert rates_2026.wa_cares.wage_base_cap is None


def test_every_filing_status_has_both_schedule_sets(rates_2026: RateTable) -> None:
    for status in FilingStatus:
        standard = rates_2026.federal_income_tax.table_for(
            filing_status=status, step2c_checked=False
        )
        checkbox = rates_2026.federal_income_tax.table_for(
            filing_status=status, step2c_checked=True
        )
        assert len(standard) == 8
        assert len(checkbox) == 8
        # Top bracket is unlimited.
        assert standard[-1].upper_bound is None
        assert checkbox[-1].upper_bound is None


def test_published_tables_are_bracket_continuous(rates_2026: RateTable) -> None:
    for status in FilingStatus:
        for step2c in (False, True):
            brackets = rates_2026.federal_income_tax.table_for(
                filing_status=status, step2c_checked=step2c
            )
            for lower, upper in itertools.pairwise(brackets):
                assert upper.threshold == lower.upper_bound


def test_standard_offset_matches_standard_deduction_minus_schedule_floor(
    rates_2026: RateTable,
) -> None:
    # The zero-tax floor of each standard schedule plus its Worksheet 1A
    # offset equals the year's standard deduction for that status.
    floors = {
        FilingStatus.MARRIED_JOINTLY: ("32200", "12900"),
        FilingStatus.SINGLE_OR_MFS: ("16100", "8600"),
        FilingStatus.HEAD_OF_HOUSEHOLD: ("24150", "8600"),
    }
    for status, (std_deduction, offset) in floors.items():
        first_taxed = rates_2026.federal_income_tax.standard[status][1]
        assert first_taxed.threshold + Decimal(offset) == Decimal(std_deduction)
        assert rates_2026.fit_standard_offsets[status] == Decimal(offset)


def test_rate_table_is_immutable(rates_2026: RateTable) -> None:
    with pytest.raises(ValidationError):
        rates_2026.tax_year = 2027  # type: ignore[misc]


def _base_data() -> dict[str, object]:
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parents[3] / "rates" / "2026.json"
    return dict(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda d: d.update(surprise_field=1), id="unknown-field"),
        pytest.param(
            lambda d: d["social_security"].update(wage_base="not-a-number"),
            id="non-numeric-decimal",
        ),
        pytest.param(
            lambda d: d["social_security"].update(employee_rate=0.062),
            id="float-value-rejected",
        ),
        pytest.param(
            lambda d: d["wa_pfml"].update(employee_share="0.5"),
            id="pfml-shares-not-1",
        ),
        pytest.param(
            lambda d: d["futa"].update(max_state_credit_rate="0.9"),
            id="credit-exceeds-gross",
        ),
        pytest.param(
            lambda d: d["federal_income_tax"]["standard"].pop("HEAD_OF_HOUSEHOLD"),
            id="missing-filing-status",
        ),
        pytest.param(
            lambda d: d["federal_income_tax"]["standard"]["SINGLE_OR_MFS"][3].update(
                threshold="999999999"
            ),
            id="brackets-not-contiguous",
        ),
        pytest.param(
            lambda d: d.update(version=0),
            id="version-below-1",
        ),
    ],
)
def test_malformed_tables_fail_at_load(mutate: object) -> None:
    data = _base_data()
    mutate(data)  # type: ignore[operator]
    with pytest.raises((ValidationError, ValueError, TypeError)):
        parse_rate_table(data)  # type: ignore[arg-type]


def test_parse_is_pure_no_input_mutation() -> None:
    data = copy.deepcopy(_base_data())
    before = copy.deepcopy(data)
    parse_rate_table(data)
    assert data == before
