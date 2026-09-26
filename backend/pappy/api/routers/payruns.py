"""PayRun CRUD + draft lifecycle endpoints, scoped to the authenticated
caller's employer (ss7.1).

Draft responses carry gross only; a finalized response also carries the full
computed payroll result (``payroll``) stored at finalization -- see
``pappy.services.payrun_service.finalize_run``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.document import Document
from pappy.models.payrun import HourLine, PayRun, PayRunCreate
from pappy.models.reports import BackfillCreate, BackfillResult, FinalizePendingResult
from pappy.services import document_service, payrun_service

router = APIRouter(prefix="/payruns", tags=["payruns"])

TableDep = Annotated[Any, Depends(get_table)]


class HourLinesUpdate(BaseModel):
    hour_lines: list[HourLine]


@router.post("/finalize-pending", response_model=FinalizePendingResult)
def finalize_pending(
    table: TableDep,
    employer_id: EmployerIdDep,
    year: int | None = None,
    employee_id: str | None = None,
) -> FinalizePendingResult:
    """Finalize pending drafts oldest-pay-date-first (Phase 6 historical
    entry). Processing stops at the first failure so wage-base caps stay
    correct; remaining drafts stay pending."""
    return payrun_service.finalize_pending_runs(
        table, employer_id, tax_year=year, employee_id=employee_id
    )


@router.post("/employees/{employee_id}", response_model=PayRun, status_code=201)
def create_payrun(
    employee_id: str, data: PayRunCreate, table: TableDep, employer_id: EmployerIdDep
) -> PayRun:
    """Open a new draft. If ``hour_lines`` is omitted, auto-populates from the
    employee's default weekly schedule (design-doc.md ss6.1)."""
    return payrun_service.create_draft(table, employer_id, employee_id, data)


@router.post("/employees/{employee_id}/backfill", response_model=BackfillResult, status_code=201)
def backfill_history(
    employee_id: str, spec: BackfillCreate, table: TableDep, employer_id: EmployerIdDep
) -> BackfillResult:
    """Create weekly DRAFT runs across a historical date range (Phase 6):
    whole weeks of history in one call, seeded from the schedule or a flat
    weekly total. Existing runs are never touched -- overlapping weeks are
    skipped. Review the drafts, then ``POST /payruns/finalize-pending``."""
    return payrun_service.create_backfill_drafts(table, employer_id, employee_id, spec)


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
    (design-doc.md ss3.2: "recompute on every change")."""
    return payrun_service.update_hours(table, employer_id, run_id, data.hour_lines)


@router.post("/{run_id}/finalize", response_model=PayRun)
def finalize_payrun(
    run_id: str, table: TableDep, employer_id: EmployerIdDep
) -> PayRun:
    """Compute withholding/net/employer accruals and lock the draft.

    The rate table is resolved server-side for the pay date's tax year, the
    W-4 in effect on the pay date is required (§5.3), and the run + YTD
    accumulator advance atomically (§4). Immutable afterward; corrections go
    through Adjustment entries (design-doc.md §3.2).
    """
    return payrun_service.finalize_run(table, employer_id, run_id)


@router.post("/{run_id}/pay-stub", response_model=Document, status_code=201)
def generate_pay_stub(
    run_id: str, table: TableDep, employer_id: EmployerIdDep
) -> Document:
    """Generate a pay stub PDF for a finalized run (§5.4, §6).

    The service owns idempotency and returns the existing document when the
    run already has a pay stub. The run must be FINALIZED first.
    """
    return document_service.generate_pay_stub(table, employer_id, run_id)
