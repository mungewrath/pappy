"""Dependent care FSA endpoints (design-doc.md §6.3).

The provider TIN is accepted transiently in the request body: it feeds one
generated PDF and is never persisted, echoed back, or logged — the same
treatment the EFW2 endpoint gives employee SSNs (§7.3). The preview endpoint
returns the money behind a claim without writing anything, so the SPA can
show the eligible amount and any over-limit warning before a receipt exists.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.document import Document
from pappy.money import Money
from pappy.services import fsa_service

router = APIRouter(prefix="/fsa", tags=["fsa"])

TableDep = Annotated[Any, Depends(get_table)]


class FsaPreviewResponse(BaseModel):
    """The figures behind a claim, computed without writing anything."""

    tax_year: int
    period_start: date
    period_end: date
    pay_run_count: int
    gross_wages: Money
    employer_fica: Money
    eligible_wages: Money
    claim_amount: Money
    already_claimed: Money
    plan_limit: Money
    remaining_before_claim: Money
    over_limit: bool
    """ Where the plan limit came from: the published statutory cap, the
    employer's plan election, or `unknown` when neither could be established.
    `unknown` means no limit check was applied — it is not a cap of zero. """
    limit_source: Literal["statutory", "plan", "unknown"]
    warning: str | None = None


class FsaReceiptRequest(BaseModel):
    """A receipt request.

    `claim_amount` omitted claims the full eligible wage total for the period
    (§6.3); set it to claim less, which is the usual mid-year case.
    `provider_tin` is transient and never stored.
    """

    employee_id: str
    period_start: date
    period_end: date
    dependent_name: str = Field(min_length=1, max_length=120)
    provider_tin: str = Field(min_length=1, max_length=20)
    claim_amount: Money | None = None


class FsaReceiptResponse(BaseModel):
    """The stored receipt plus the figures it was built from.

    `warning` is present when the claim exceeds the plan limit. The receipt is
    still generated — the employer can submit a smaller claim, and refusing
    to produce the paperwork would not help them.
    """

    document: Document
    figures: FsaPreviewResponse


@router.get("/preview", response_model=FsaPreviewResponse)
def preview(
    table: TableDep,
    employer_id: EmployerIdDep,
    employee_id: str,
    period_start: date,
    period_end: date,
    claim_amount: Money | None = None,
) -> FsaPreviewResponse:
    """Eligible wages, cumulative claimed, and any over-limit warning."""
    figures = fsa_service.fsa_figures(
        table,
        employer_id,
        employee_id=employee_id,
        period_start=period_start,
        period_end=period_end,
        claim_amount=claim_amount,
    )
    return FsaPreviewResponse(
        tax_year=figures.tax_year,
        period_start=figures.period_start,
        period_end=figures.period_end,
        pay_run_count=figures.pay_run_count,
        gross_wages=figures.gross_wages,
        employer_fica=figures.employer_fica,
        eligible_wages=figures.eligible_wages,
        claim_amount=figures.claim_amount,
        already_claimed=figures.already_claimed,
        plan_limit=figures.plan_limit,
        remaining_before_claim=figures.remaining_before_claim,
        over_limit=figures.over_limit,
        limit_source=figures.limit_source,
        warning=figures.warning,
    )


@router.post("/receipts", response_model=FsaReceiptResponse, status_code=201)
def create_receipt(
    data: FsaReceiptRequest, table: TableDep, employer_id: EmployerIdDep
) -> FsaReceiptResponse:
    """Generate and store a dependent care FSA receipt (§6.3)."""
    doc, figures = fsa_service.generate_receipt(
        table,
        employer_id,
        employee_id=data.employee_id,
        period_start=data.period_start,
        period_end=data.period_end,
        dependent_name=data.dependent_name,
        provider_tin=data.provider_tin,
        claim_amount=data.claim_amount,
    )
    return FsaReceiptResponse(
        document=doc,
        figures=FsaPreviewResponse(
            tax_year=figures.tax_year,
            period_start=figures.period_start,
            period_end=figures.period_end,
            pay_run_count=figures.pay_run_count,
            gross_wages=figures.gross_wages,
            employer_fica=figures.employer_fica,
            eligible_wages=figures.eligible_wages,
            claim_amount=figures.claim_amount,
            already_claimed=figures.already_claimed,
            plan_limit=figures.plan_limit,
            remaining_before_claim=figures.remaining_before_claim,
            over_limit=figures.over_limit,
            limit_source=figures.limit_source,
            warning=figures.warning,
        ),
    )
