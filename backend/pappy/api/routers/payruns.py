"""PayRun CRUD + draft lifecycle endpoints, nested under an employer.

Withholding/net pay are not part of the response yet — see
`pappy.calc.gross` and `pappy.services.payrun_service` module docstrings.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pappy.api.deps import get_table
from pappy.models.payrun import HourLine, PayRun, PayRunCreate
from pappy.services import payrun_service

router = APIRouter(prefix="/employers/{employer_id}/payruns", tags=["payruns"])

TableDep = Annotated[Any, Depends(get_table)]


class HourLinesUpdate(BaseModel):
    hour_lines: list[HourLine]


class FinalizeRequest(BaseModel):
    rate_table_version: int | None = None


@router.post("/employees/{employee_id}", response_model=PayRun, status_code=201)
def create_payrun(
    employer_id: str, employee_id: str, data: PayRunCreate, table: TableDep
) -> PayRun:
    """Open a new draft. If `hour_lines` is omitted, auto-populates from the
    employee's default weekly schedule (design-doc.md §6.1)."""
    return payrun_service.create_draft(table, employer_id, employee_id, data)


@router.get("", response_model=list[PayRun])
def list_payruns(employer_id: str, table: TableDep, year: int | None = None) -> list[PayRun]:
    return payrun_service.list_runs(table, employer_id, year=year)


@router.get("/{run_id}", response_model=PayRun)
def get_payrun(employer_id: str, run_id: str, table: TableDep) -> PayRun:
    return payrun_service.get_draft_or_run(table, employer_id, run_id)


@router.put("/{run_id}/hours", response_model=PayRun)
def update_hours(employer_id: str, run_id: str, data: HourLinesUpdate, table: TableDep) -> PayRun:
    """Replace the hour lines on a DRAFT run; gross is recomputed
    (design-doc.md §3.2: "recompute on every change")."""
    return payrun_service.update_hours(table, employer_id, run_id, data.hour_lines)


@router.post("/{run_id}/finalize", response_model=PayRun)
def finalize_payrun(
    employer_id: str, run_id: str, data: FinalizeRequest, table: TableDep
) -> PayRun:
    """Lock the draft. Immutable afterward; corrections go through Adjustment
    entries (design-doc.md §3.2), not implemented in this pass."""
    return payrun_service.finalize_run(
        table, employer_id, run_id, rate_table_version=data.rate_table_version
    )
