"""W-2 box summary builder (design-doc.md §6.5).

Computes the *values* that go in the employee copies' boxes from the year's
folded runs. Copy A filing happens through SSA Business Services Online
(EFW2, see `pappy.calc.efw2`); the app never prints Copy A.

Box semantics for a household employer:

- Box 1 = total cash wages. Household employees have no pre-tax benefit
  deductions in scope, so all wages are taxable federal wages.
- Boxes 3/4 — Social Security wages (the wage-base-capped slices actually
  taxed) and the employee share withheld.
- Boxes 5/6 — Medicare wages (all cash wages; uncapped) and everything
  withheld under Medicare, the Additional Medicare Tax included.
- Box 14 — informational entries only; Washington has no state income tax,
  so the WA PFML and WA Cares employee contributions are reported there.
"""

from __future__ import annotations

from pappy.calc.tax_year import RunContribution, aggregate_year
from pappy.models.reports import W2Box14Item, W2Summary
from pappy.money import Money


def build_w2_summary(
    contributions: list[RunContribution],
    *,
    tax_year: int,
    employer_name: str,
    employer_ein: str,
    employee_id: str,
    employee_name: str,
) -> W2Summary:
    """Fold one employee's runs into W-2 box values."""
    year = aggregate_year(contributions)

    ee_ss_withheld = Money.sum([c.ee_social_security for c in contributions])
    ee_medicare_withheld = Money.sum(
        [c.ee_medicare + c.additional_medicare for c in contributions]
    )
    pfml = Money.sum([c.wa_pfml_employee for c in contributions])
    cares = Money.sum([c.wa_cares_employee for c in contributions])

    box14 = [
        W2Box14Item(label="WA PFML employee contribution", amount=pfml),
        W2Box14Item(label="WA Cares Fund employee contribution", amount=cares),
    ]

    return W2Summary(
        tax_year=tax_year,
        employer_name=employer_name,
        employer_ein=employer_ein,
        employee_id=employee_id,
        employee_name=employee_name,
        box1_wages=year.gross,
        box2_fit_withheld=year.federal_income_tax_withheld,
        box3_ss_wages=Money(year.ss_wages),
        box4_ss_tax_withheld=ee_ss_withheld,
        box5_medicare_wages=year.gross,
        box6_medicare_tax_withheld=ee_medicare_withheld,
        box14_items=[item for item in box14 if item.amount > Money(0)],
    )
