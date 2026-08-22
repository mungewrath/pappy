"""PayRun and HourLine entities (design-doc.md §3.1, §3.2).

A DRAFT run carries only gross pay and the overtime-premium breakdown
(design-doc.md §5.4), recomputed on every hour-line edit. At finalization the
full withholding/net/employer-accrual result from `pappy.calc.payroll`
(§5.1 steps 2-4) is computed once and stored on the run together with the
rate-table version used (§5.2: "compute once, store the result") — after that
the run is immutable.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field, model_validator

from pappy.calc.gross import GrossPayResult, compute_gross_pay
from pappy.calc.payroll import PayrollResult
from pappy.decimals import StrictDecimal
from pappy.models.common import HourCategory, OvertimePolicy, PayRunStatus


class HourLine(BaseModel):
    """One line of worked (or paid-but-not-worked) time on a pay run."""

    line_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    work_date: date
    hours: StrictDecimal
    category: HourCategory = HourCategory.REGULAR

    @model_validator(mode="after")
    def _hours_non_negative(self) -> HourLine:
        if self.hours < 0:
            raise ValueError("hours cannot be negative")
        return self


class PayRunCreate(BaseModel):
    """Fields needed to open a new draft pay run."""

    period_start: date
    period_end: date
    pay_date: date
    hour_lines: list[HourLine] = []

    @model_validator(mode="after")
    def _period_is_ordered(self) -> PayRunCreate:
        if self.period_end < self.period_start:
            raise ValueError("period_end cannot be before period_start")
        return self


class PayRunUpdate(BaseModel):
    """Editing a DRAFT run's hour lines (design-doc.md §3.2)."""

    hour_lines: list[HourLine]


class PayRun(BaseModel):
    """Stored pay run.

    Key: PK=`EMPLOYER#<id>`, SK=`PAYRUN#<payDate>#<runId>` (design-doc.md §4).

    States: DRAFT -> FINALIZED -> (VOIDED). A DRAFT is freely editable and
    recomputed on every hour-line change; once FINALIZED it is immutable and
    corrections happen via a separate Adjustment entry (design-doc.md §3.2).
    """

    employer_id: str
    employee_id: str
    run_id: str
    status: PayRunStatus = PayRunStatus.DRAFT
    period_start: date
    period_end: date
    pay_date: date
    hour_lines: list[HourLine] = []
    gross: GrossPayResult
    payroll: PayrollResult | None = None
    rate_table_version: int | None = None
    created_at: datetime
    updated_at: datetime
    finalized_at: datetime | None = None
    voided_at: datetime | None = None

    @classmethod
    def new_draft(
        cls,
        employer_id: str,
        employee_id: str,
        run_id: str,
        data: PayRunCreate,
        *,
        hourly_rate: StrictDecimal,
        overtime_policy: OvertimePolicy,
    ) -> PayRun:
        now = datetime.now(UTC)
        gross = compute_gross_pay(
            hour_lines=data.hour_lines,
            hourly_rate=hourly_rate,
            overtime_policy=overtime_policy,
        )
        return cls(
            employer_id=employer_id,
            employee_id=employee_id,
            run_id=run_id,
            status=PayRunStatus.DRAFT,
            period_start=data.period_start,
            period_end=data.period_end,
            pay_date=data.pay_date,
            hour_lines=data.hour_lines,
            gross=gross,
            created_at=now,
            updated_at=now,
        )

    def with_recomputed_hours(
        self,
        hour_lines: list[HourLine],
        *,
        hourly_rate: StrictDecimal,
        overtime_policy: OvertimePolicy,
    ) -> PayRun:
        """Return a copy with new hour lines and gross recomputed.

        Only valid while the run is a DRAFT — enforced by the service layer,
        which owns the state-machine rule (design-doc.md §3.2), not the model.
        """
        gross = compute_gross_pay(
            hour_lines=hour_lines, hourly_rate=hourly_rate, overtime_policy=overtime_policy
        )
        return self.model_copy(
            update={
                "hour_lines": hour_lines,
                "gross": gross,
                "updated_at": datetime.now(UTC),
            }
        )

    def finalize(self, *, rate_table_version: int, payroll: PayrollResult) -> PayRun:
        """Transition DRAFT -> FINALIZED, storing the computed payroll result.

        The full computation and the rate-table version are recorded here
        (design principle 3, "compute once, store the result"); the
        transaction that also advances the YTD accumulator (design-doc.md §4)
        lives in the repo layer.
        """
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "status": PayRunStatus.FINALIZED,
                "payroll": payroll,
                "rate_table_version": rate_table_version,
                "finalized_at": now,
                "updated_at": now,
            }
        )

    def void(self) -> PayRun:
        now = datetime.now(UTC)
        return self.model_copy(
            update={"status": PayRunStatus.VOIDED, "voided_at": now, "updated_at": now}
        )
