"""Document listing and download endpoints (design-doc.md §3.1)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
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
    """Lifetime of `url` when it is a pre-signed S3 URL; not meaningful for
    `via: api`, where the URL carries no signature."""
    expires_in: int
    """How the client should fetch `url`.

    `url` — open it directly; a pre-signed S3 URL needs no credentials.
    `api` — fetch it *with* the caller's `Authorization` header. Required for
    the local-filesystem transport, where the artifact is served by the API
    itself. A browser cannot attach a header to a top-level navigation, so
    these must be fetched by the client rather than opened.
    """
    via: Literal["url", "api"]


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


@router.get("/{doc_id}/content")
def download_document_content(
    doc_id: str,
    table: TableDep,
    employer_id: EmployerIdDep,
) -> FileResponse:
    """Stream a document's bytes, for the local-filesystem transport.

    `GET /{doc_id}/download` returns a pre-signed S3 URL in deployed
    environments, which the SPA opens directly. With no bucket configured
    (docker-compose dev) the artifact is a file on the API container's disk,
    where a `file://` URL is unreachable from the browser — so the local
    branch of that endpoint points here instead, and this carries the bytes
    over HTTP.

    Employer-scoped like every other document read, and the path comes from
    the stored record rather than the request, so an authenticated caller can
    only reach their own documents (§7.1, §7.3). 404 when a bucket *is*
    configured: there is no reason to proxy bytes the client could have
    fetched from S3 directly.

    The media type is derived from the stored filename rather than assumed to
    be a PDF — a year-view CSV served as `application/pdf` would be handed to
    the browser as a broken document.
    """
    content = document_service.get_local_content(table, employer_id, doc_id)
    return FileResponse(
        content.path,
        media_type=content.media_type,
        filename=content.filename,
        headers={"X-Content-SHA256": content.sha256},
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
