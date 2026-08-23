"""PayRun CRUD + draft lifecycle endpoints, scoped to the authenticated
caller's employer (§7.1).

Draft responses carry gross only; a finalized response also carries the full
computed payroll result (`payroll`) stored at finalization — see
`pappy.services.payrun_service.finalize_run`.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.payrun import HourLine, PayRun, PayRunCreate
from pappy.services import payrun_service

router = APIRouter(prefix="/payruns", tags=["payruns"])

TableDep = Annotated[Any, Depends(get_table)]


class HourLinesUpdate(BaseModel):
    hour_lines: list[HourLine]


@router.post("/employees/{employee_id}", response_model=PayRun, status_code=201)
def create_payrun(
    employee_id: str, data: PayRunCreate, table: TableDep, employer_id: EmployerIdDep
) -> PayRun:
    """Open a new draft. If `hour_lines` is omitted, auto-populates from the
    employee's default weekly schedule (design-doc.md §6.1)."""
    return payrun_service.create_draft(table, employer_id, employee_id, data)


@router.get("", response_model=list[PayRun])
def list_payruns(table: TableDep, employer_id: EmployerIdDep, year: int | None = None) -> list[PayRun]:
    return payrun_service.list_runs(table, employer_id, year=year)


@router.get("/{run_id}", response_model=PayRun)
def get_payrun(run_id: str, table: TableDep, employer_id: EmployerIdDep) -> PayRun:
    return payrun_service.get_draft_or_run(table, employer_id, run_id)


@router.put("/{run_id}/hours", response_model=PayRun)
def update_hours(
    run_id: str, data: HourLinesUpdate, table: TableDep, employer_id: EmployerIdDep
) -> PayRun:
    """Replace the hour lines on a DRAFT run; gross is recomputed
    (design-doc.md §3.2: "recompute on every change")."""
    return payrun_service.update_hours(table, employer_id, run_id, data.hour_lines)


@router.post("/{run_id}/finalize", response_model=PayRun)
def finalize_payrun(run_id: str, table: TableDep, employer_id: EmployerIdDep) -> PayRun:
    """Compute withholding/net/employer accruals and lock the draft.

    The rate table is resolved server-side for the pay date's tax year, the
    W-4 in effect on the pay date is required (§5.3), and the run + YTD
    accumulator advance atomically (§4). Immutable afterward; corrections go
    through Adjustment entries (design-doc.md §3.2)."""
    return payrun_service.finalize_run(table, employer_id, run_id)
