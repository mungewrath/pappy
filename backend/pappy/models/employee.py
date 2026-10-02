"""Employee entity (design-doc.md §3.1). The nanny."""

from __future__ import annotations

from datetime import UTC, date, datetime

from pydantic import BaseModel

from pappy.decimals import StrictDecimal
from pappy.models._update import _set_fields
from pappy.models.common import Address, OvertimePolicy


class DefaultScheduleLine(BaseModel):
    """One line of the employee's default weekly schedule.

    `weekday` is 0=Monday .. 6=Sunday, matching `date.weekday()`, so seeding
    a draft `PayRun`'s hour lines from the schedule is a straightforward
    date-arithmetic operation (design-doc.md §6.1).
    """

    weekday: int
    hours: StrictDecimal

    def model_post_init(self, context: object, /) -> None:
        if not 0 <= self.weekday <= 6:
            raise ValueError("weekday must be 0 (Monday) through 6 (Sunday)")


class EmployeeCreate(BaseModel):
    full_name: str
    address: Address
    hire_date: date
    hourly_rate: StrictDecimal
    overtime_policy: OvertimePolicy = OvertimePolicy.APPLIES
    default_schedule: list[DefaultScheduleLine] = []


class EmployeeUpdate(BaseModel):
    full_name: str | None = None
    address: Address | None = None
    hourly_rate: StrictDecimal | None = None
    overtime_policy: OvertimePolicy | None = None
    default_schedule: list[DefaultScheduleLine] | None = None
    termination_date: date | None = None


class Employee(BaseModel):
    """Stored employee record.

    Key: PK=`EMPLOYER#<id>`, SK=`EMPLOYEE#<empId>` (design-doc.md §4).

    Note: SSN and bank details are deliberately absent from this model —
    per design-doc.md §7.3 they are envelope-encrypted and handled by a
    dedicated path, out of scope for this CRUD pass.
    """

    employer_id: str
    employee_id: str
    full_name: str
    address: Address
    hire_date: date
    termination_date: date | None = None
    hourly_rate: StrictDecimal
    overtime_policy: OvertimePolicy = OvertimePolicy.APPLIES
    default_schedule: list[DefaultScheduleLine] = []
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, employer_id: str, employee_id: str, data: EmployeeCreate) -> Employee:
        now = datetime.now(UTC)
        return cls(
            employer_id=employer_id,
            employee_id=employee_id,
            full_name=data.full_name,
            address=data.address,
            hire_date=data.hire_date,
            hourly_rate=data.hourly_rate,
            overtime_policy=data.overtime_policy,
            default_schedule=data.default_schedule,
            created_at=now,
            updated_at=now,
        )

    def apply_update(self, data: EmployeeUpdate) -> Employee:
        return self.model_copy(
            update={**_set_fields(data), "updated_at": datetime.now(UTC)}
        )
