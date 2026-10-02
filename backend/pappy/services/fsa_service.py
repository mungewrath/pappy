"""Dependent care FSA reimbursement receipts (design-doc.md §6.3).

A DCFSA claim needs a provider-signed receipt showing the amount paid for
services in a period. This service:

1. sums the *gross wages* for finalized pay runs in the requested service
   range — the default eligible basis;
2. compares the claim against what has already been claimed this tax year and
   the applicable plan limit, warning when it would exceed;
3. renders the receipt PDF and stores it as a hashed document, like every
   other artifact.

Two deliberate choices worth stating:

**Cumulative claimed is derived, not tracked.** The running total is a sum
over the `claimed_amount` already recorded on this year's FSA receipts. A
separate counter could drift from the receipts actually issued; summing the
receipts cannot.

**The provider TIN is transient.** It arrives in the request, reaches one
generated PDF, and is never written down — the same treatment §7.3 gives the
employee SSN on the EFW2 path, and for the same reason.

Employer taxes are excluded by default and included on request (§6.3's
"configurable"). When included, only the *employer FICA halves* count:
Social Security and Medicare are the wages-based taxes a plan may treat as
eligible, whereas FUTA, WA UI, and the WA PFML employer share are not
dependent-care wages and are left out deliberately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from pappy.documents.fsa_receipt import generate_fsa_receipt_pdf
from pappy.models.common import PayRunStatus
from pappy.models.document import Document, DocumentType
from pappy.models.employee import Employee
from pappy.money import Money
from pappy.repo import document_repo, employee_repo, employer_repo, payrun_repo, rate_table_repo
from pappy.repo.bucket import get_bucket

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


@dataclass(frozen=True)
class FsaFigures:
    """The money behind a claim, and whether it fits the plan.

    `eligible_wages` is what the ledger says the service period was worth;
    `claim_amount` is what would actually be claimed, which may be less — a
    claim is a request for reimbursement, not a statement that every dollar
    earned was spent on the dependent.
    """

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
    limit_source: Literal["statutory", "plan", "unknown"]

    @property
    def warning(self) -> str | None:
        """Human-readable over-claim warning, or None when the claim fits."""
        if not self.over_limit:
            return None
        return (
            f"Claiming {self.claim_amount} would bring this year's total to "
            f"{self.already_claimed + self.claim_amount}, over the "
            f"{self.plan_limit} dependent care FSA limit. Reduce the claim "
            f"amount, or confirm the plan limit on the Employer profile."
        )


def _statutory_limit(
    table: Table, employer_id: str, tax_year: int
) -> tuple[Money, Literal["statutory", "plan", "unknown"]]:
    """The applicable annual limit: the plan's election, else the statutory cap.

    The statutory figure is rate-table data (§5.2) — it is republished each
    year — while a plan may elect less, which lives on the employer profile.

    Returns `Money.zero` with source `"unknown"` when the cap cannot be
    established, either because no rate table is seeded for the year or
    because the stored table predates the `dependent_care_fsa` block. §5.2
    makes those rows immutable, so an unfixed deployment stays in that state
    indefinitely; a zero limit disables the over-claim check rather than
    blocking every reimbursement, and the UI labels it as unknown instead of
    implying a real cap of zero.
    """
    employer = employer_repo.get(table, employer_id)
    if employer.fsa_plan_limit is not None:
        return employer.fsa_plan_limit, "plan"
    rates = rate_table_repo.latest_for_year(table, tax_year)
    if rates is None or rates.dependent_care_fsa is None:
        return Money.zero, "unknown"
    return rates.dependent_care_fsa.annual_limit, "statutory"


def _period_wages(
    table: Table, employer_id: str, employee_id: str, start: date, end: date
) -> tuple[Money, Money, int]:
    """Sum gross wages and employer FICA for finalized runs in the range.

    Only *finalized* runs count: a draft's wages are not yet owed and may
    still change, so a claim must never be built on one. Attributed by pay
    date, matching the cash-basis reasoning the quarterly estimates use
    (§5.3) — the money is the employer's on the day the check is written.
    """
    runs = payrun_repo.list_for_employer(table, employer_id, start=start, end=end)
    gross = Money.zero
    employer_fica = Money.zero
    count = 0
    for run in runs:
        if (
            run.employee_id != employee_id
            or run.status != PayRunStatus.FINALIZED
            or run.payroll is None
        ):
            continue
        gross = gross + run.payroll.gross
        employer_fica = employer_fica + (
            run.payroll.employer_accruals.social_security
            + run.payroll.employer_accruals.medicare
        )
        count += 1
    return gross, employer_fica, count


def already_claimed(table: Table, employer_id: str, tax_year: int) -> Money:
    """Total claimed against the plan so far this tax year.

    Derived by summing the receipts on file rather than kept in a counter, so
    it cannot disagree with the documents actually issued.
    """
    receipts = document_repo.list_for_employer(
        table, employer_id, tax_year=tax_year, doc_type=DocumentType.FSA_RECEIPT
    )
    amounts = [r.claimed_amount for r in receipts if r.claimed_amount is not None]
    return Money.sum(amounts)


def fsa_figures(
    table: Table,
    employer_id: str,
    *,
    employee_id: str,
    period_start: date,
    period_end: date,
    claim_amount: Money | None = None,
) -> FsaFigures:
    """Compute the claim figures for a service period, writing nothing.

    `claim_amount` defaults to the full eligible wage total (§6.3's "sums the
    gross wages for runs in that range"); supplying a smaller amount claims
    part of it, which is how a mid-year reimbursement normally works.
    """
    if period_start > period_end:
        raise ValueError("period_start must not be after period_end")
    employer = employer_repo.get(table, employer_id)
    gross, employer_fica, count = _period_wages(
        table, employer_id, employee_id, period_start, period_end
    )
    eligible = gross + employer_fica if employer.fsa_include_employer_taxes else gross
    amount = eligible if claim_amount is None else claim_amount
    if amount.amount < 0:
        raise ValueError("claim_amount cannot be negative")

    tax_year = period_end.year
    limit, limit_source = _statutory_limit(table, employer_id, tax_year)
    claimed = already_claimed(table, employer_id, tax_year)
    remaining = limit - claimed
    over_limit = limit.amount > 0 and (claimed + amount).amount > limit.amount

    return FsaFigures(
        tax_year=tax_year,
        period_start=period_start,
        period_end=period_end,
        pay_run_count=count,
        gross_wages=gross,
        employer_fica=employer_fica,
        eligible_wages=eligible,
        claim_amount=amount,
        already_claimed=claimed,
        plan_limit=limit,
        remaining_before_claim=remaining,
        over_limit=over_limit,
        limit_source=limit_source,
    )


def _wage_basis_note(include_employer_taxes: bool) -> str:
    if include_employer_taxes:
        return (
            "Amount derived from gross wages paid plus the employer's Social "
            "Security and Medicare contributions for the service period."
        )
    return "Amount derived from gross wages paid for the service period."


def generate_receipt(
    table: Table,
    employer_id: str,
    *,
    employee_id: str,
    period_start: date,
    period_end: date,
    dependent_name: str,
    provider_tin: str,
    claim_amount: Money | None = None,
) -> tuple[Document, FsaFigures]:
    """Render and store an FSA receipt. Returns the document and its figures.

    The figures come back alongside the document so the caller can surface an
    over-claim warning *after* the fact without a second round trip — the
    receipt is still written when the claim exceeds the limit, because the
    employer's remedy is to submit a smaller claim, not to have the app
    silently refuse to produce the paperwork (§6.3).
    """
    employer = employer_repo.get(table, employer_id)
    employee = employee_repo.get(table, employer_id, employee_id)
    figures = fsa_figures(
        table,
        employer_id,
        employee_id=employee_id,
        period_start=period_start,
        period_end=period_end,
        claim_amount=claim_amount,
    )

    pdf_bytes = generate_fsa_receipt_pdf(
        employer_name=employer.legal_name,
        employer_address_line1=employer.address.line1,
        employer_address_line2=employer.address.line2,
        employer_address_city=employer.address.city,
        employer_address_state=employer.address.state,
        employer_address_zip=employer.address.zip_code,
        provider_name=_provider_name(employee),
        provider_tin=provider_tin,
        provider_address_line1=employee.address.line1,
        provider_address_line2=employee.address.line2,
        provider_address_city=employee.address.city,
        provider_address_state=employee.address.state,
        provider_address_zip=employee.address.zip_code,
        dependent_name=dependent_name,
        service_start=period_start.isoformat(),
        service_end=period_end.isoformat(),
        amount_paid=str(figures.claim_amount.amount),
        wage_basis_note=_wage_basis_note(employer.fsa_include_employer_taxes),
        tax_year=figures.tax_year,
    )

    s3_key = (
        f"{employer_id}/fsa-receipts/{figures.tax_year}/"
        f"{period_start.isoformat()}-{period_end.isoformat()}-{employee_id}.pdf"
    )
    bucket = get_bucket()
    sha256 = bucket.put(s3_key, pdf_bytes, content_type="application/pdf")

    doc = Document.new(
        employer_id=employer_id,
        document_type=DocumentType.FSA_RECEIPT,
        tax_year=figures.tax_year,
        s3_key=s3_key,
        sha256=sha256,
        pay_run_ids=[],
        period_start=period_start,
        period_end=period_end,
        claimed_amount=figures.claim_amount,
        filename=f"fsa-receipt-{period_start.isoformat()}-{period_end.isoformat()}.pdf",
    )
    document_repo.put(table, doc)
    return doc, figures


def _provider_name(employee: Employee) -> str:
    """The care provider named on the receipt.

    §6.3 asks the receipt to name a provider with an address and a TIN. The
    only party to this payroll with both is the employee, so that is the
    default — the nanny is the person whose care the FSA reimburses and whose
    signature the plan needs.
    """
    return employee.full_name
