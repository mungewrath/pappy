"""W-4 elections (design-doc.md §3.1, §5.3).

An `W4Election` is an effective-dated child of the employee record, so a
mid-year re-election never rewrites earlier finalized runs: a pay run
resolves the election in effect on its pay date (§5.3, "Mid-year W-4
changes"). Storage and resolution live with the employee repo; this module
holds only the value object.

Field names follow the Form W-4 steps they come from.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from pappy.decimals import StrictDecimal
from pappy.models.common import FilingStatus


class W4Election(BaseModel):
    """One employee's federal income tax withholding elections.

    `dependent_credit_amount` is the annual Step 3 total, `other_income`
    and `deductions` are the annual Step 4(a)/4(b) amounts, and
    `extra_withholding` is the per-period Step 4(c) amount. All monetary
    fields are clamped at zero — a W-4 cannot elect negative amounts.
    """

    effective_date: date
    filing_status: FilingStatus = FilingStatus.SINGLE_OR_MFS
    multiple_jobs_step2c: bool = False
    dependent_credit_amount: StrictDecimal = Field(default=Decimal(0), ge=0)
    other_income: StrictDecimal = Field(default=Decimal(0), ge=0)
    deductions: StrictDecimal = Field(default=Decimal(0), ge=0)
    extra_withholding: StrictDecimal = Field(default=Decimal(0), ge=0)
