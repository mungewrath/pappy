"""Document listing and download endpoints (design-doc.md §3.1)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.document import Document, DocumentType
from pappy.services import document_service

router = APIRouter(prefix="/documents", tags=["documents"])

TableDep = Annotated[Any, Depends(get_table)]


class DownloadResponse(BaseModel):
    url: str
    sha256: str
    filename: str
    expires_in: int


@router.get("", response_model=list[Document])
def list_documents(
    table: TableDep,
    employer_id: EmployerIdDep,
    tax_year: int | None = None,
    doc_type: DocumentType | None = None,
) -> list[Document]:
    """List generated documents, optionally filtered by year and type."""
    return document_service.list_documents(
        table, employer_id, tax_year=tax_year, doc_type=doc_type
    )


@router.get("/{doc_id}/download", response_model=DownloadResponse)
def download_document(
    doc_id: str,
    table: TableDep,
    employer_id: EmployerIdDep,
) -> DownloadResponse:
    """Get a pre-signed download URL for an existing document."""
    result = document_service.get_download_url(table, employer_id, doc_id)
    return DownloadResponse.model_validate(result)
