"""Tax-year artifact endpoints (design-doc.md §9 Phase 6).

All artifacts derive from finalized runs only and are scoped to the
authenticated caller's employer (§7.1). The EFW2 endpoint accepts SSNs
transiently in its request body — they feed one file generation and are
never persisted or logged (§7.3).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.reports import (
    EarningsSummary,
    QuarterlyEstimates,
    ScheduleHWorksheet,
    W2Summary,
)
from pappy.services import tax_year_service

router = APIRouter(prefix="/tax-years", tags=["tax"])

TableDep = Annotated[Any, Depends(get_table)]


class Efw2Request(BaseModel):
    """Transient SSNs keyed by employee ID — blank/absent produces a
    preview record BSO would reject."""

    employee_ssns: dict[str, str] = {}


@router.get("/{tax_year}/1040-es", response_model=QuarterlyEstimates)
def quarterly_estimates(tax_year: int, table: TableDep, employer_id: EmployerIdDep) -> QuarterlyEstimates:
    """Quarterly estimated-tax figures from finalized runs (§5.3, §6.6):
    withheld FIT plus both halves of FICA, with FUTA on top."""
    return tax_year_service.quarterly_estimates(table, employer_id, tax_year)


@router.get("/{tax_year}/schedule-h", response_model=ScheduleHWorksheet)
def schedule_h(tax_year: int, table: TableDep, employer_id: EmployerIdDep) -> ScheduleHWorksheet:
    """Schedule H line values plus the contributing-run worksheet (§6.4)."""
    return tax_year_service.schedule_h_worksheet(table, employer_id, tax_year)


@router.get("/{tax_year}/w2", response_model=list[W2Summary])
def w2_summaries(tax_year: int, table: TableDep, employer_id: EmployerIdDep) -> list[W2Summary]:
    """W-2 box values for every employee with finalized runs in the year."""
    return tax_year_service.w2_summaries(table, employer_id, tax_year)


@router.get("/{tax_year}/earnings-summary", response_model=list[EarningsSummary])
def earnings_summary(
    tax_year: int, table: TableDep, employer_id: EmployerIdDep
) -> list[EarningsSummary]:
    """Annual earnings summary per employee (§5.4): overtime-premium
    breakdown, withholding year totals, wage-base consumption."""
    return tax_year_service.earnings_summaries(table, employer_id, tax_year)


@router.post("/{tax_year}/efw2", response_class=PlainTextResponse)
def efw2(
    tax_year: int,
    request: Efw2Request,
    table: TableDep,
    employer_id: EmployerIdDep,
) -> PlainTextResponse:
    """The SSA EFW2 upload file (§6.5), generated on demand.

    SSNs live in the request body only for this one generation — they are
    never stored, echoed back, or logged (§7.3).
    """
    content = tax_year_service.efw2_file(
        table, employer_id, tax_year, employee_ssns=request.employee_ssns
    )
    return PlainTextResponse(
        content,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="EFW2-{tax_year}.txt"'},
    )
