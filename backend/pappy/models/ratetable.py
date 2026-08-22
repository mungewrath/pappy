"""Versioned statutory rate tables (design-doc.md §3.1, §5.2).

Rates are data, not code: every statutory number lives in
`rates/<tax_year>.json` at the repository root, is parsed into these
Pydantic models with `Decimal` fields (so a malformed value fails here,
at load, not at payroll time), and is immutable once a pay run references
its `(tax_year, version)` pair.

The 2026 file carries values verified against current publications:

- IRS Publication 15-T (2026) percentage-method tables, transcribed
  verbatim from irs.gov/publications/p15t, including Worksheet 1A's
  standard-deduction offsets ($12,900 MFJ / $8,600 otherwise)
- SSA 2026 contribution and benefit base ($184,500), announced Oct 2025
- IRS Publication 926 (2026) household coverage thresholds ($3,000 FICA;
  $1,000 quarterly FUTA) and FUTA parameters
- WA ESD / paidleave.wa.gov 2026 PFML premium (1.13%, split 71.43/28.57),
  WA Cares premium (0.58%, employee-only, no wage cap for 2026), and UI
  taxable wage base ($78,200; the experience rate itself is per-employer,
  assigned annually by ESD)

Each January a new `<year>.json` must be added after verifying every
value against that year's publications (§5.2 annual rollover checklist).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pappy.decimals import StrictDecimal
from pappy.models.common import FilingStatus


class FederalTaxBracket(BaseModel):
    """One row of a Pub. 15-T percentage-method rate schedule.

    Mirrors the published columns: `threshold` ("At least"), `upper_bound`
    ("But less than" — `None` on the unlimited top row), `base_tax` (the
    tentative amount at the threshold) and `marginal_rate`.
    """

    model_config = ConfigDict(frozen=True)

    threshold: StrictDecimal
    upper_bound: StrictDecimal | None = None
    base_tax: StrictDecimal
    marginal_rate: StrictDecimal


class FitTableSet(BaseModel):
    """Both Pub. 15-T schedule sets for one tax year.

    `standard` applies when the W-4 Step 2(c) checkbox is unchecked;
    `step2c_checkbox` when it is checked. Each maps filing status to an
    ascending bracket list.
    """

    model_config = ConfigDict(frozen=True)

    standard: dict[FilingStatus, list[FederalTaxBracket]]
    step2c_checkbox: dict[FilingStatus, list[FederalTaxBracket]]

    def table_for(self, *, filing_status: FilingStatus, step2c_checked: bool) -> list[
        FederalTaxBracket
    ]:
        if step2c_checked:
            return self.step2c_checkbox[filing_status]
        return self.standard[filing_status]


class SocialSecurityConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    employee_rate: StrictDecimal
    employer_rate: StrictDecimal
    wage_base: StrictDecimal


class MedicareConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    rate: StrictDecimal
    additional_rate: StrictDecimal
    additional_threshold: StrictDecimal


class FutaConfig(BaseModel):
    """Federal unemployment parameters.

    The effective employer rate is `gross_rate - max_state_credit_rate`
    while the state credit applies (design-doc.md §5.1: "FUTA (0.6%
    effective on the first $7,000 when the state credit applies)"). A
    credit-reduction year lowers `max_state_credit_rate`, which is data,
    not code.
    """

    model_config = ConfigDict(frozen=True)

    gross_rate: StrictDecimal
    max_state_credit_rate: StrictDecimal
    wage_base: StrictDecimal

    @property
    def effective_rate(self) -> StrictDecimal:
        return self.gross_rate - self.max_state_credit_rate


class WaPfmlConfig(BaseModel):
    """WA Paid Family & Medical Leave premium and its statutory split."""

    model_config = ConfigDict(frozen=True)

    premium_rate: StrictDecimal
    employee_share: StrictDecimal
    employer_share: StrictDecimal
    # PFML premiums stop at the Social Security wage base.
    wage_base: StrictDecimal


class WaCaresConfig(BaseModel):
    """WA Cares Fund premium (employee-only).

    `wage_base_cap` is `None` for 2026 — no cap — but the field exists so
    a future legislative cap stays configuration data.
    """

    model_config = ConfigDict(frozen=True)

    premium_rate: StrictDecimal
    wage_base_cap: StrictDecimal | None = None


class WaUiConfig(BaseModel):
    """WA unemployment insurance.

    Only the taxable wage base is statutory; the premium itself is the
    employer's ESD-assigned experience rate, supplied per computation.
    """

    model_config = ConfigDict(frozen=True)

    wage_base: StrictDecimal


class HouseholdCoverageConfig(BaseModel):
    """Household-employer coverage thresholds (Pub. 926).

    Below the FICA cash-wage threshold no social security/Medicare taxes
    are owed for the year; below the FUTA quarterly threshold no FUTA is
    owed. These feed setup guidance and Schedule H, not per-run math:
    a household under them is not running weekly payroll.
    """

    model_config = ConfigDict(frozen=True)

    fica_cash_wage_threshold: StrictDecimal
    futa_quarterly_cash_wage_threshold: StrictDecimal


class RateTable(BaseModel):
    """All statutory values for one tax year, versioned.

    Frozen and closed to extra fields so a typo'd or stale JSON file fails
    loudly at load. Correcting a table mid-year means shipping version
    n+1; already-finalized runs keep pointing at version n (§5.2).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    tax_year: int
    version: int = Field(ge=1)
    source_notes: str | None = None
    pay_periods_per_year: int = Field(default=52, ge=1)
    fit_standard_offsets: dict[FilingStatus, StrictDecimal]
    federal_income_tax: FitTableSet
    social_security: SocialSecurityConfig
    medicare: MedicareConfig
    futa: FutaConfig
    wa_pfml: WaPfmlConfig
    wa_cares: WaCaresConfig
    wa_ui: WaUiConfig
    household_coverage: HouseholdCoverageConfig

    @property
    def rate_table_id(self) -> str:
        return f"{self.tax_year}#v{self.version}"


def _validate_bracket_list(brackets: list[FederalTaxBracket], label: str) -> None:
    if not brackets:
        raise ValueError(f"{label}: bracket list is empty")
    previous: FederalTaxBracket | None = None
    for bracket in brackets:
        if bracket.threshold < 0 or bracket.base_tax < 0:
            raise ValueError(f"{label}: negative threshold or base tax in {bracket}")
        if not 0 <= bracket.marginal_rate <= 1:
            raise ValueError(f"{label}: marginal_rate out of range in {bracket}")
        if previous is not None:
            if bracket.threshold <= previous.threshold:
                raise ValueError(
                    f"{label}: thresholds must strictly ascend at {bracket.threshold}"
                )
            if previous.upper_bound != bracket.threshold:
                raise ValueError(
                    f"{label}: brackets are not contiguous "
                    f"({previous.upper_bound} vs next threshold {bracket.threshold})"
                )
        previous = bracket
    assert previous is not None  # narrowed by the empty check above
    if previous.upper_bound is not None:
        raise ValueError(f"{label}: only the final bracket may have no upper bound")


def parse_rate_table(data: dict[str, Any]) -> RateTable:
    """Parse and validate a raw JSON dict into a `RateTable`.

    Raises `pydantic.ValidationError` or `ValueError` on malformed input —
    deliberately, so bad statutory data cannot reach payroll time (§5.2).
    """
    table = RateTable.model_validate(data)
    for set_name, table_set in (
        ("standard", table.federal_income_tax.standard),
        ("step2c_checkbox", table.federal_income_tax.step2c_checkbox),
    ):
        statuses = set(table_set)
        if statuses != set(FilingStatus):
            missing = sorted(s.value for s in set(FilingStatus) - statuses)
            raise ValueError(f"federal_income_tax.{set_name} missing statuses: {missing}")
        for status, brackets in table_set.items():
            _validate_bracket_list(brackets, f"federal_income_tax.{set_name}.{status.value}")
    pfml = table.wa_pfml
    if pfml.employee_share + pfml.employer_share != 1:
        raise ValueError("wa_pfml shares do not sum to 1")
    if table.futa.effective_rate < 0:
        raise ValueError("futa state credit exceeds the gross FUTA rate")
    return table


def load_rate_table(path: Path) -> RateTable:
    """Load a `rates/<year>.json` file from disk."""
    with path.open(encoding="utf-8") as f:
        return parse_rate_table(json.load(f))
