"""Tax-year artifact endpoints (design-doc.md §9 Phase 6).

All artifacts derive from finalized runs only and are scoped to the
authenticated caller's employer (§7.1). The EFW2 endpoint accepts SSNs
transiently in its request body — they feed one file generation and are
never persisted or logged (§7.3).
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.document import Document
from pappy.models.reports import (
    EarningsSummary,
    QuarterlyEstimates,
    ScheduleHWorksheet,
    W2Summary,
)
from pappy.models.year_view import YearView
from pappy.services import tax_year_service, year_view_service

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


# --- Year view and CSV export (design-doc.md §6.2) ----------------------------


@router.get("/{tax_year}/year-view", response_model=YearView)
def year_view(
    tax_year: int,
    table: TableDep,
    employer_id: EmployerIdDep,
    start: date | None = None,
    end: date | None = None,
    employee_id: str | None = None,
) -> YearView:
    """Every finalized run in the year with running YTD totals (§6.2).

    Filterable by pay-date range and employee. Drafts are excluded — they have
    no stored computation yet and belong in the pay-run list.
    """
    return year_view_service.year_view(
        table,
        employer_id,
        tax_year=tax_year,
        start=start,
        end=end,
        employee_id=employee_id,
    )


@router.post("/{tax_year}/year-view.csv", response_model=Document, status_code=201)
def export_year_view(
    tax_year: int,
    table: TableDep,
    employer_id: EmployerIdDep,
    start: date | None = None,
    end: date | None = None,
    employee_id: str | None = None,
) -> Document:
    """Write the year view to the document store as a hashed CSV artifact.

    Returns the Document rather than the bytes so the SPA downloads it
    through the same pre-signed path as every other artifact (§7.3) — the CSV
    is an archived document, not a transient response.
    """
    return year_view_service.export_year_view_csv(
        table,
        employer_id,
        tax_year=tax_year,
        start=start,
        end=end,
        employee_id=employee_id,
    )
