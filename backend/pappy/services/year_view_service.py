"""Year-view business logic (design-doc.md §6.2).

Reads finalized runs and hands them to the pure aggregation in
`pappy.calc.year_view`. The service's only jobs are the ones that genuinely
need the database: reading the ledger, resolving employee names for display,
and writing the CSV export to the document store.

Like the tax-year artifacts, everything here consumes the *stored* per-run
computations — no rate table or W-4 is resolved at report time, so the year
view of a 2026 tax year is identical no matter when it is generated.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from pappy.calc.year_view import build_year_view, year_view_csv
from pappy.models.document import Document, DocumentType
from pappy.models.year_view import YearView
from pappy.repo import document_repo, employee_repo, payrun_repo
from pappy.repo.bucket import get_bucket

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table


def year_view(
    table: Table,
    employer_id: str,
    *,
    tax_year: int,
    start: date | None = None,
    end: date | None = None,
    employee_id: str | None = None,
) -> YearView:
    """The §6.2 year view for one tax year, optionally narrowed by date range.

    A date range is resolved as a sort-key range on the pay-run partition
    (§4), so a filtered view is still one `Query` rather than a full-year read
    plus a Python-side filter.
    """
    runs = payrun_repo.list_for_employer(table, employer_id, start=start, end=end)
    names = {
        e.employee_id: e.full_name for e in employee_repo.list_for_employer(table, employer_id)
    }
    return build_year_view(
        runs,
        tax_year=tax_year,
        employee_names=names,
        period_start=start,
        period_end=end,
        employee_id=employee_id,
    )


def export_year_view_csv(
    table: Table,
    employer_id: str,
    *,
    tax_year: int,
    start: date | None = None,
    end: date | None = None,
    employee_id: str | None = None,
) -> Document:
    """Write the year view to the document store as a CSV artifact.

    Stored rather than streamed so the export is part of the audited archive
    like every other artifact: it lands in S3 under a content hash, appears in
    the document list with the runs it covers, and can be proven byte-identical
    to the file originally issued (§6.2).

    Each export is a new document — a re-export with different filters is a
    genuinely different artifact, and suppressing it would leave an employer
    unable to evidence what they actually sent their accountant.
    """
    view = year_view(
        table,
        employer_id,
        tax_year=tax_year,
        start=start,
        end=end,
        employee_id=employee_id,
    )
    csv_bytes = year_view_csv(view)

    # The artifact's tax year is the year the export *covers*; a cross-year
    # range is filed under the year it starts in.
    artifact_year = start.year if start is not None else tax_year
    doc_type = DocumentType.YEAR_VIEW_CSV
    filename = f"year-view-{artifact_year}.csv"
    suffix = f"{start.isoformat()}-{end.isoformat()}" if start and end else str(artifact_year)
    s3_key = f"{employer_id}/year-view-csv/{artifact_year}/{suffix}.csv"

    bucket = get_bucket()
    sha256 = bucket.put(s3_key, csv_bytes, content_type="text/csv")

    doc = Document.new(
        employer_id=employer_id,
        document_type=doc_type,
        tax_year=artifact_year,
        s3_key=s3_key,
        sha256=sha256,
        pay_run_ids=[row.run_id for row in view.rows],
        period_start=start,
        period_end=end,
        filename=filename,
    )
    document_repo.put(table, doc)
    return doc
