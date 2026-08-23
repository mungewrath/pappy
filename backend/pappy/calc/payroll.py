"""Payroll computation engine (design-doc.md §5.1).

Pure calculation, no AWS imports. Given one pay run's gross, the W-4
election in effect on its pay date, a versioned rate table, and
year-to-date context, computes:

1. employee withholding lines — Social Security (wage-base capped),
   Medicare plus Additional Medicare above its threshold, federal income
   tax (`pappy.calc.fit`, §5.3), WA PFML employee share, WA Cares
   employee share (with exemption flag support);
2. net pay — gross minus withholding (post-tax deductions arrive with
   the Adjustment entity, Phase 2);
3. employer accruals — matching SS/Medicare, FUTA at its effective rate,
   WA UI at the employer's ESD-assigned rate, WA PFML employer share.

Rounding is per-line half-up at the cent (§5.5): each Money line is
quantized exactly once from full-precision Decimals.

Washington has no state income tax; that line is absent by design.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, computed_field

from pappy.calc.fit import MissingW4Error, compute_fit
from pappy.decimals import StrictDecimal
from pappy.models.ratetable import RateTable
from pappy.models.w4 import W4Election
from pappy.money import Money


class YtdContext(BaseModel):
    """Year-to-date covered wages already paid this tax year.

    Wage-base caps (Social Security, FUTA, WA UI, WA PFML) are applied
    against these amounts without re-reading the year's runs (§4); the
    stored accumulators are advanced transactionally at finalization.
    """

    social_security_wages: StrictDecimal = Decimal(0)
    medicare_wages: StrictDecimal = Decimal(0)
    futa_wages: StrictDecimal = Decimal(0)
    wa_ui_wages: StrictDecimal = Decimal(0)
    wa_pfml_wages: StrictDecimal = Decimal(0)


class TaxableWages(BaseModel):
    """The slice of this run's gross each cap-limited tax applies to."""

    social_security: StrictDecimal
    medicare: StrictDecimal
    additional_medicare: StrictDecimal
    futa: StrictDecimal
    wa_ui: StrictDecimal
    wa_pfml: StrictDecimal


class EmployeeWithholding(BaseModel):
    """Employee-side deduction lines, in stub display order (§5.4).

    `total` is serialized so clients can display it without doing money
    arithmetic themselves (§5.5: the frontend formats, never computes).
    """

    social_security: Money
    medicare: Money
    additional_medicare: Money
    federal_income_tax: Money
    wa_pfml_employee: Money
    wa_cares_employee: Money

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> Money:
        return Money.sum(
            [
                self.social_security,
                self.medicare,
                self.additional_medicare,
                self.federal_income_tax,
                self.wa_pfml_employee,
                self.wa_cares_employee,
            ]
        )


class EmployerAccruals(BaseModel):
    """Employer-side tax accruals (§5.1 step 4).

    Not withheld from the employee; these drive Schedule H and the
    quarterly 1040-ES figures.
    """

    social_security: Money
    medicare: Money
    futa: Money
    wa_ui: Money
    wa_pfml_employer: Money

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total(self) -> Money:
        return Money.sum(
            [
                self.social_security,
                self.medicare,
                self.futa,
                self.wa_ui,
                self.wa_pfml_employer,
            ]
        )


class PayrollResult(BaseModel):
    """The complete computed result for one pay run (stored at finalize)."""

    gross: Money
    taxable: TaxableWages
    withholding: EmployeeWithholding
    net_pay: Money
    employer_accruals: EmployerAccruals


def compute_payroll(
    *,
    gross: Money,
    w4: W4Election,
    rates: RateTable,
    ytd: YtdContext | None = None,
    wa_ui_experience_rate: StrictDecimal = Decimal(0),
    pfml_small_employer_exempt: bool = True,
    wa_cares_exempt: bool = False,
) -> PayrollResult:
    """Compute all withholding, net pay, and employer accruals for a run.

    Raises `MissingW4Error` when `w4` is None — a missing election blocks
    computation rather than silently defaulting (§5.3).

    WA household employers with fewer than 50 employees owe no PFML
    employer share (they must still collect the employee share), hence
    `pfml_small_employer_exempt` defaults to True.
    """
    if w4 is None:
        raise MissingW4Error("a W-4 election is required to compute payroll")
    ytd = ytd if ytd is not None else YtdContext()

    amount = gross.amount

    # --- wage-base-capped taxable slices -----------------------------------
    ss_room = _remaining(rates.social_security.wage_base, ytd.social_security_wages)
    taxable_ss = min(amount, ss_room)
    addl_room = _remaining(rates.medicare.additional_threshold, ytd.medicare_wages)
    taxable_addl = max(Decimal(0), amount - addl_room)
    pfml_room = _remaining(rates.wa_pfml.wage_base, ytd.wa_pfml_wages)
    taxable_pfml = min(amount, pfml_room)
    futa_room = _remaining(rates.futa.wage_base, ytd.futa_wages)
    taxable_futa = min(amount, futa_room)
    ui_room = _remaining(rates.wa_ui.wage_base, ytd.wa_ui_wages)
    taxable_ui = min(amount, ui_room)

    # --- employee withholding (§5.1 step 2) ---------------------------------
    ee_ss = Money(taxable_ss * rates.social_security.employee_rate)
    ee_medicare = Money(amount * rates.medicare.rate)
    ee_addl_medicare = Money(taxable_addl * rates.medicare.additional_rate)
    fit = compute_fit(period_gross=gross, w4=w4, rates=rates)
    premium = rates.wa_pfml.premium_rate
    ee_pfml = Money(taxable_pfml * premium * rates.wa_pfml.employee_share)
    cares_rate = rates.wa_cares.premium_rate
    cares_base = amount if rates.wa_cares.wage_base_cap is None else min(
        amount, max(Decimal(0), rates.wa_cares.wage_base_cap - ytd.social_security_wages)
    )
    ee_cares = Money(0) if wa_cares_exempt else Money(cares_base * cares_rate)

    withholding = EmployeeWithholding(
        social_security=ee_ss,
        medicare=ee_medicare,
        additional_medicare=ee_addl_medicare,
        federal_income_tax=fit,
        wa_pfml_employee=ee_pfml,
        wa_cares_employee=ee_cares,
    )

    # --- employer accruals (§5.1 step 4) ------------------------------------
    er_ss = Money(taxable_ss * rates.social_security.employer_rate)
    er_medicare = Money(amount * rates.medicare.rate)
    futa = Money(taxable_futa * rates.futa.effective_rate)
    ui = Money(taxable_ui * wa_ui_experience_rate)
    er_pfml = (
        Money(0)
        if pfml_small_employer_exempt
        else Money(taxable_pfml * premium * rates.wa_pfml.employer_share)
    )

    accruals = EmployerAccruals(
        social_security=er_ss,
        medicare=er_medicare,
        futa=futa,
        wa_ui=ui,
        wa_pfml_employer=er_pfml,
    )

    # --- net pay (§5.1 step 3) ----------------------------------------------
    net_pay = gross - withholding.total

    return PayrollResult(
        gross=gross,
        taxable=TaxableWages(
            social_security=taxable_ss,
            medicare=amount,
            additional_medicare=taxable_addl,
            futa=taxable_futa,
            wa_ui=taxable_ui,
            wa_pfml=taxable_pfml,
        ),
        withholding=withholding,
        net_pay=net_pay,
        employer_accruals=accruals,
    )


def _remaining(wage_base: StrictDecimal, ytd_wages: StrictDecimal) -> StrictDecimal:
    return max(Decimal(0), wage_base - ytd_wages)
