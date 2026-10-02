"""Document generation + storage service (design-doc.md §3.1, §7.3).

The first artifact (Phase 3) is the pay stub PDF. The service:

1. reads the finalized pay run, employee, employer, and YTD context;
2. generates the PDF via `pappy.documents.pay_stub`;
3. uploads the bytes to S3 (or the local file-system fallback);
4. writes a `Document` record to DynamoDB with the S3 key and SHA-256;
5. returns the Document record.

Subsequent phases plug in additional generators (FSA receipt, Schedule H,
W-2, earnings summary) by adding a new `DocumentType` and a new `_generate_*`
function — the store-and-index flow stays the same.
"""

from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict
from urllib.parse import quote

from pappy.documents.pay_stub import generate_pay_stub_pdf
from pappy.models.common import PayRunStatus
from pappy.models.document import Document, DocumentType
from pappy.repo import document_repo, employee_repo, employer_repo, payrun_repo
from pappy.repo.bucket import get_bucket
from pappy.repo.exceptions import InvalidStateError, NotFoundError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

    from pappy.models.payrun import PayRun


DOWNLOAD_URL_TTL_SECONDS = 900

# Fallback matches the documented local setup (uvicorn on :8000, `compose.yaml`
# sets it explicitly). This is the *host-visible* address — the browser has to be
# able to reach it, so it is deliberately not the container's own network name.
DEFAULT_API_BASE_URL = "http://localhost:8000"


def api_base_url() -> str:
    """Externally reachable base URL of this API, for links handed to a client.

    Only the local-filesystem transport needs it: deployed documents are served
    by pre-signed S3 URLs the client opens directly (§7.3).
    """
    return os.environ.get("PAPPY_API_BASE_URL", DEFAULT_API_BASE_URL).rstrip("/")


@dataclass(frozen=True)
class YtdAmounts:
    gross: str
    social_security: str
    medicare: str
    additional_medicare: str
    federal_income_tax: str
    wa_pfml_employee: str
    wa_cares_employee: str
    total_withholding: str
    net_pay: str


class DownloadInfo(TypedDict):
    url: str
    sha256: str
    filename: str
    expires_in: int
    via: str


@dataclass(frozen=True)
class LocalContent:
    """A stored document resolved to a file on this process's own disk."""

    path: Path
    filename: str
    sha256: str
    media_type: str


def media_type_for(filename: str) -> str:
    """MIME type for a stored artifact, from its filename.

    The S3 transport records the content type at upload time, so a
    pre-signed download already carries the right header. The local
    filesystem transport has no such metadata — `bucket.put` writes raw
    bytes — so the type is derived from the stored filename, which is
    server-generated and always carries the artifact's real extension.
    """
    guessed, _encoding = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def generate_pay_stub(
    table: Table,
    employer_id: str,
    run_id: str,
) -> Document:
    """Generate a pay stub PDF for a finalized run.

    Returns the `Document` record (§5.4). Idempotent: if a PAY_STUB
    document already exists for this run, the existing record is returned
    without regenerating.
    """
    run = payrun_repo.find(table, employer_id, run_id)
    if run.status != PayRunStatus.FINALIZED:
        raise InvalidStateError(
            f"Cannot generate pay stub for a {run.status.value} PayRun"
        )
    if run.payroll is None:
        raise InvalidStateError(
            f"PayRun {run.run_id} is finalized but has no stored payroll result"
        )

    # Idempotency: return existing document if already generated.
    existing_docs = document_repo.list_for_pay_run(table, employer_id, run_id)
    existing = next(
        (d for d in existing_docs if d.document_type == DocumentType.PAY_STUB),
        None,
    )
    if existing is not None:
        return existing

    employer = employer_repo.get(table, employer_id)
    employee = employee_repo.get(table, employer_id, run.employee_id)

    # YTD: sum all finalized payrolls for this employee through this run.
    ytd = _compute_ytd(table, employer_id, run)

    payroll = run.payroll
    w = payroll.withholding

    withholding_current = {
        "social_security": str(w.social_security.amount),
        "medicare": str(w.medicare.amount),
        "additional_medicare": str(w.additional_medicare.amount),
        "federal_income_tax": str(w.federal_income_tax.amount),
        "wa_pfml_employee": str(w.wa_pfml_employee.amount),
        "wa_cares_employee": str(w.wa_cares_employee.amount),
    }

    pdf_bytes = generate_pay_stub_pdf(
        employer_name=employer.legal_name,
        employer_ein=employer.ein,
        employer_address_line1=employer.address.line1,
        employer_address_line2=employer.address.line2,
        employer_address_city=employer.address.city,
        employer_address_state=employer.address.state,
        employer_address_zip=employer.address.zip_code,
        employee_name=employee.full_name,
        employee_address_line1=employee.address.line1,
        employee_address_line2=employee.address.line2,
        employee_address_city=employee.address.city,
        employee_address_state=employee.address.state,
        employee_address_zip=employee.address.zip_code,
        employee_hire_date=employee.hire_date.isoformat(),
        period_start=run.period_start.isoformat(),
        period_end=run.period_end.isoformat(),
        pay_date=run.pay_date.isoformat(),
        regular_hours=str(run.gross.regular_hours),
        overtime_hours=str(run.gross.overtime_hours),
        other_paid_hours=str(run.gross.other_paid_hours),
        unpaid_hours=str(run.gross.unpaid_hours),
        hourly_rate=str(run.gross.hourly_rate),
        effective_overtime_rate=(
            str(run.gross.effective_overtime_rate)
            if run.gross.effective_overtime_rate is not None
            else None
        ),
        overtime_workweek=(
            f"{run.period_start.isoformat()} - {run.period_end.isoformat()}"
            if run.gross.overtime_hours > 0
            else None
        ),
        straight_time_pay=str(run.gross.straight_time_pay.amount),
        overtime_premium_pay=str(run.gross.overtime_premium_pay.amount),
        gross=str(run.gross.gross.amount),
        gross_ytd=ytd.gross,
        withholding_current=withholding_current,
        withholding_ytd={
            "social_security": ytd.social_security,
            "medicare": ytd.medicare,
            "additional_medicare": ytd.additional_medicare,
            "federal_income_tax": ytd.federal_income_tax,
            "wa_pfml_employee": ytd.wa_pfml_employee,
            "wa_cares_employee": ytd.wa_cares_employee,
        },
        total_withholding_current=str(w.total.amount),
        total_withholding_ytd=ytd.total_withholding,
        net_pay_current=str(payroll.net_pay.amount),
        net_pay_ytd=ytd.net_pay,
    )

    bucket = get_bucket()
    filename = f"pay-stub-{run.pay_date.isoformat()}.pdf"
    s3_key = f"{employer_id}/pay-stubs/{run.pay_date.year}/{run.run_id}.pdf"
    sha256 = bucket.put(s3_key, pdf_bytes)

    doc = Document.new(
        employer_id=employer_id,
        document_type=DocumentType.PAY_STUB,
        tax_year=run.pay_date.year,
        s3_key=s3_key,
        sha256=sha256,
        pay_run_ids=[run.run_id],
        pay_date=run.pay_date,
        filename=filename,
    )
    document_repo.put(table, doc)
    return doc


def list_documents(
    table: Table,
    employer_id: str,
    *,
    tax_year: int | None = None,
    doc_type: DocumentType | None = None,
) -> list[Document]:
    """List generated documents, optionally filtered."""
    return document_repo.list_for_employer(
        table, employer_id, tax_year=tax_year, doc_type=doc_type
    )


def get_download_url(
    table: Table, employer_id: str, doc_id: str
) -> DownloadInfo:
    """Get a download URL for an existing document, plus how to fetch it.

    With an S3 bucket configured this is a pre-signed HTTPS URL, the deployed
    path — the browser fetches from S3 directly and the bytes never pass
    through the API (§7.3). The client may open such a URL as-is.

    Without one, the document is a file on this process's disk, so the URL
    points at `GET /documents/{id}/content` and must be fetched *with* the
    caller's credentials. That cannot be a plain browser navigation — a
    top-level navigation carries no `Authorization` header, so the request
    would arrive anonymous and be resolved against the wrong employer. Hence
    `via`: the client fetches the bytes itself and saves them.
    """
    doc = document_repo.get_by_id(table, employer_id, doc_id)
    bucket = get_bucket()
    if bucket.is_s3:
        url: str = bucket.presigned_url(
            doc.s3_key, expires_in=DOWNLOAD_URL_TTL_SECONDS
        )
        via = "url"
    else:
        url = f"{api_base_url()}/documents/{quote(doc.doc_id)}/content"
        via = "api"
    return {
        "url": url,
        "sha256": doc.sha256,
        "filename": doc.filename,
        "expires_in": DOWNLOAD_URL_TTL_SECONDS,
        "via": via,
    }


def get_local_content(
    table: Table, employer_id: str, doc_id: str
) -> LocalContent:
    """Resolve a document to a readable file for the local transport.

    The counterpart to `get_download_url`'s local branch. The document lookup
    is what enforces scoping (§7.1): a doc_id belonging to another employer is
    a 404 here, and the resolved `s3_key` comes from DynamoDB rather than the
    request, so nothing client-supplied reaches the filesystem.
    """
    doc = document_repo.get_by_id(table, employer_id, doc_id)
    bucket = get_bucket()
    if bucket.is_s3:
        # Deployed environments serve documents by pre-signed URL (§7.3); this
        # endpoint is the local-filesystem stand-in and has nothing to add.
        raise NotFoundError("DocumentContent", doc_id)
    path = bucket.local_path(doc.s3_key)
    if not path.is_file():
        raise NotFoundError("DocumentContent", doc_id)
    return LocalContent(
        path=path,
        filename=doc.filename,
        sha256=doc.sha256,
        media_type=media_type_for(doc.filename),
    )


def _compute_ytd(
    table: Table,
    employer_id: str,
    current_run: PayRun,
) -> YtdAmounts:
    """Sum finalized payrolls for this employee through the current run.

    Runs are included if they are finalized and their pay date is
    <= the current run's pay date. This gives the stub accurate YTD
    columns.
    """
    from pappy.money import Money

    year_runs = payrun_repo.list_for_employer(
        table, employer_id, year=current_run.pay_date.year
    )

    total_gross = Money.zero
    ss = Money.zero
    medicare = Money.zero
    addl_medicare = Money.zero
    fit = Money.zero
    pfml = Money.zero
    cares = Money.zero
    total_wh = Money.zero
    net = Money.zero

    for r in year_runs:
        if (
            r.employee_id == current_run.employee_id
            and r.status == PayRunStatus.FINALIZED
            and r.payroll is not None
            and r.pay_date <= current_run.pay_date
        ):
            w = r.payroll.withholding
            total_gross = total_gross + r.payroll.gross
            ss = ss + w.social_security
            medicare = medicare + w.medicare
            addl_medicare = addl_medicare + w.additional_medicare
            fit = fit + w.federal_income_tax
            pfml = pfml + w.wa_pfml_employee
            cares = cares + w.wa_cares_employee
            total_wh = total_wh + w.total
            net = net + r.payroll.net_pay

    return YtdAmounts(
        gross=str(total_gross.amount),
        social_security=str(ss.amount),
        medicare=str(medicare.amount),
        additional_medicare=str(addl_medicare.amount),
        federal_income_tax=str(fit.amount),
        wa_pfml_employee=str(pfml.amount),
        wa_cares_employee=str(cares.amount),
        total_withholding=str(total_wh.amount),
        net_pay=str(net.amount),
    )
