"""Document entity (design-doc.md §3.1).

A generated artifact: pay stub, FSA receipt, Schedule H, W-2, W-3,
Form 1040-ES, or annual earnings summary. Each document is produced from
finalized pay runs, stored in S3 with a SHA-256 content hash, and served
via short-lived pre-signed URLs — never public reads (§7.3).

Phase 3 delivers the first artifact (pay stub PDF) and the document
store foundation. Later phases add the remaining generators.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    """Kinds of generated artifact (design-doc.md §3.1)."""

    PAY_STUB = "PAY_STUB"
    FSA_RECEIPT = "FSA_RECEIPT"
    SCHEDULE_H = "SCHEDULE_H"
    W2 = "W2"
    W3 = "W3"
    FORM_1040ES = "FORM_1040ES"
    EARNINGS_SUMMARY = "EARNINGS_SUMMARY"


class Document(BaseModel):
    """Stored document record.

    Key: PK=EMPLOYER#<id>, SK=DOC#<taxYear>#<type>#<docId>
    (design-doc.md §4). The S3 object is the actual artifact; this
    record is the index entry that links pay runs to their documents and
    enables hash-based verification of re-generated files.
    """

    employer_id: str
    doc_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    document_type: DocumentType
    tax_year: int
    pay_run_ids: list[str] = Field(default_factory=list)
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
            filename=filename or f"{document_type.value}.pdf",
            created_at=now,
        )
