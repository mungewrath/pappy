"""YTD accumulator entity (design-doc.md §3.1, §4).

One item per (employer, employee, tax year), advanced transactionally when a
pay run is finalized (design-doc.md §4): the `TransactWriteItems` in
`pappy.repo.payrun_repo.finalize` writes the finalized run and adds this
year's wage-base slices in one atomic operation, conditioned on the run still
being DRAFT. Wage-base caps (Social Security, FUTA, WA UI, WA PFML) are then
always correct without re-reading the year's runs — though the year *can* be
recomputed from scratch as a consistency check (§8).

The accumulator stores *covered wages* (the capped slices), not Money: these
are internal quantities consumed by `pappy.calc.payroll.YtdContext`, never
displayed or serialized to documents, so they stay full-precision Decimals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel

from pappy.calc.payroll import TaxableWages
from pappy.decimals import StrictDecimal


class YtdAccumulator(BaseModel):
    """Covered-wage totals for one employee's tax year so far.

    Key: PK=`EMPLOYER#<id>`, SK=`YTD#<taxYear>#<empId>` (design-doc.md §4).
    """

    employer_id: str
    employee_id: str
    tax_year: int
    social_security_wages: StrictDecimal = Decimal(0)
    medicare_wages: StrictDecimal = Decimal(0)
    futa_wages: StrictDecimal = Decimal(0)
    wa_ui_wages: StrictDecimal = Decimal(0)
    wa_pfml_wages: StrictDecimal = Decimal(0)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def apply_taxable(self, taxable: TaxableWages) -> YtdAccumulator:
        """Return a copy with one run's capped wage slices added.

        Pure — the persisted update happens atomically in the finalize
        transaction; this mirrors exactly what that transaction's `ADD`
        clauses will do, so callers can hold the post-write value without a
        re-read.
        """
        return self.model_copy(
            update={
                "social_security_wages": self.social_security_wages + taxable.social_security,
                "medicare_wages": self.medicare_wages + taxable.medicare,
                "futa_wages": self.futa_wages + taxable.futa,
                "wa_ui_wages": self.wa_ui_wages + taxable.wa_ui,
                "wa_pfml_wages": self.wa_pfml_wages + taxable.wa_pfml,
                "updated_at": datetime.now(UTC),
            }
        )
