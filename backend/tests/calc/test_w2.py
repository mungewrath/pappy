"""W-2 box summary (design-doc.md §6.5).

Box 1 = all cash wages; Box 3/4 the SS-capped slice and employee share;
Box 5/6 Medicare wages and everything withheld (Additional included);
WA PFML/Cares surface as informational Box 14 entries.
"""

from datetime import date
from decimal import Decimal

from pappy.calc.tax_year import RunContribution
from pappy.calc.w2 import build_w2_summary
from pappy.money import Money


def test_w2_boxes_for_one_employee_year() -> None:
    contribution = RunContribution(
        run_id="run-1",
        employee_id="nanny-1",
        pay_date=date(2026, 1, 16),
        gross=Money("1187.50"),
        federal_income_tax_withheld=Money("100.58"),
        ee_social_security=Money("73.63"),
        er_social_security=Money("73.63"),
        ee_medicare=Money("17.22"),
        er_medicare=Money("17.22"),
        additional_medicare=Money("0.00"),
        wa_pfml_employee=Money("9.59"),
        wa_cares_employee=Money("6.89"),
        ss_wages=Decimal("1187.50"),
    )
    summary = build_w2_summary(
        [contribution],
        tax_year=2026,
        employer_name="Jane Doe",
        employer_ein="12-3456789",
        employee_id="nanny-1",
        employee_name="Nanny Smith",
    )

    assert str(summary.box1_wages) == "1187.50"
    assert str(summary.box2_fit_withheld) == "100.58"
    assert str(summary.box3_ss_wages) == "1187.50"
    assert str(summary.box4_ss_tax_withheld) == "73.63"  # employee share only
    assert str(summary.box5_medicare_wages) == "1187.50"
    assert str(summary.box6_medicare_tax_withheld) == "17.22"

    box14 = {item.label: item.amount for item in summary.box14_items}
    assert str(box14["WA PFML employee contribution"]) == "9.59"
    assert str(box14["WA Cares Fund employee contribution"]) == "6.89"


def test_zero_box14_entries_are_dropped() -> None:
    summary = build_w2_summary(
        [], tax_year=2026, employer_name="J", employer_ein="1", employee_id="e", employee_name="N"
    )
    assert summary.box14_items == []
