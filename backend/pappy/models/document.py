"""Document entity (design-doc.md §3.1).

A generated artifact: pay stub, FSA receipt, Schedule H, W-2, W-3,
Form 1040-ES, annual earnings summary, or a year-view CSV export. Each
document is produced from finalized pay runs, stored in S3 with a SHA-256
content hash, and served via short-lived pre-signed URLs — never public
reads (§7.3).

Phase 3 delivers the first artifact (pay stub PDF) and the document
store foundation. Later phases add the remaining generators.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from enum import Enum

from pydantic import BaseModel, Field

from pappy.money import Money


class DocumentType(str, Enum):
    """Kinds of generated artifact (design-doc.md §3.1)."""

    PAY_STUB = "PAY_STUB"
    FSA_RECEIPT = "FSA_RECEIPT"
    SCHEDULE_H = "SCHEDULE_H"
    W2 = "W2"
    W3 = "W3"
    FORM_1040ES = "FORM_1040ES"
    EARNINGS_SUMMARY = "EARNINGS_SUMMARY"
    YEAR_VIEW_CSV = "YEAR_VIEW_CSV"


class Document(BaseModel):
    """Stored document record.

    Key: PK=EMPLOYER#<id>, SK=DOC#<taxYear>#<type>#<docId>
    (design-doc.md §4). The S3 object is the actual artifact; this
    record is the index entry that links pay runs to their documents and
    enables hash-based verification of re-generated files.

    `pay_run_ids` are opaque identifiers, so `pay_date` is stored alongside
    them for the artifacts that cover one run (a pay stub) — the archive
    lists by pay date, not by id. Documents spanning a range of runs (a
    year-view CSV, an FSA receipt) instead record that range in
    `period_start`/`period_end`; a document covering a whole tax year
    without a narrower range leaves both unset.

    `claimed_amount` is set only on FSA receipts: the amount the employer
    actually claimed against the plan. Cumulative claimed is *derived* by
    summing this field over the year's receipts rather than tracked
    separately, so it cannot drift from the receipts actually issued
    (§6.3).
    """

    employer_id: str
    doc_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    document_type: DocumentType
    tax_year: int
    pay_run_ids: list[str] = Field(default_factory=list)
    pay_date: date | None = None
    period_start: date | None = None
    period_end: date | None = None
    claimed_amount: Money | None = None
    s3_key: str
    sha256: str
    filename: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @classmethod
    def new(
        cls,
        *,
        employer_id: str,
        document_type: DocumentType,
        tax_year: int,
        s3_key: str,
        sha256: str,
        pay_run_ids: list[str] | None = None,
        pay_date: date | None = None,
        period_start: date | None = None,
        period_end: date | None = None,
        claimed_amount: Money | None = None,
        filename: str = "",
    ) -> Document:
        now = datetime.now(UTC)
        return cls(
            employer_id=employer_id,
            doc_id=uuid.uuid4().hex,
            document_type=document_type,
            tax_year=tax_year,
            s3_key=s3_key,
            sha256=sha256,
            pay_run_ids=pay_run_ids or [],
            pay_date=pay_date,
            period_start=period_start,
            period_end=period_end,
            claimed_amount=claimed_amount,
            filename=filename or f"{document_type.value}.pdf",
            created_at=now,
        )
