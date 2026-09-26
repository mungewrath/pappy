"""Document repo — PK=`EMPLOYER#<id>`, SK=`DOC#<taxYear>#<type>#<docId>`.

Tracks generated artifacts (pay stubs, W-2s, Schedule H, etc.) per design-doc.md
§3.1 and §4. Documents are written once at generation time and never updated;
listing and retrieval are the only read patterns.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Key

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.document import Document, DocumentType
from pappy.repo import keys
from pappy.repo.exceptions import NotFoundError


def _to_item(doc: Document) -> dict[str, Any]:
    item = doc.model_dump(mode="json")
    item["pk"] = keys.employer_pk(doc.employer_id)
    item["sk"] = keys.doc_sk(doc.tax_year, doc.document_type.value, doc.doc_id)
    return item


def _from_item(item: dict[str, Any]) -> Document:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return Document.model_validate(body)


def put(table: Table, doc: Document) -> Document:
    table.put_item(Item=_to_item(doc))
    return doc


def get(
    table: Table, employer_id: str, tax_year: int, doc_type: DocumentType, doc_id: str
) -> Document:
    response = table.get_item(
        Key={
            "pk": keys.employer_pk(employer_id),
            "sk": keys.doc_sk(tax_year, doc_type.value, doc_id),
        }
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("Document", doc_id)
    return _from_item(item)


def get_by_id(table: Table, employer_id: str, doc_id: str) -> Document:
    """Retrieve a document by doc_id alone (scans the employer's partition)."""
    all_docs = list_for_employer(table, employer_id)
    matches = [doc for doc in all_docs if doc.doc_id == doc_id]
    if not matches:
        raise NotFoundError("Document", doc_id)
    return matches[0]


def list_for_employer(
    table: Table,
    employer_id: str,
    *,
    tax_year: int | None = None,
    doc_type: DocumentType | None = None,
) -> list[Document]:
    prefix = keys.doc_sk_prefix(tax_year)
    response = table.query(
        KeyConditionExpression=Key("pk").eq(keys.employer_pk(employer_id))
        & Key("sk").begins_with(prefix)
    )
    results = [_from_item(item) for item in response.get("Items", [])]
    if doc_type is not None:
        results = [doc for doc in results if doc.document_type == doc_type]
    return results


def list_for_pay_run(table: Table, employer_id: str, run_id: str) -> list[Document]:
    """All documents that reference a specific pay run.

    Scans the employer's document partition — fine at household scale.
    """
    all_docs = list_for_employer(table, employer_id)
    return [doc for doc in all_docs if run_id in doc.pay_run_ids]


def get_for_pay_run(
    table: Table,
    employer_id: str,
    run_id: str,
    doc_type: DocumentType,
) -> Document | None:
    """Find the first document of the given type for a pay run, or None."""
    all_docs = list_for_employer(table, employer_id, doc_type=doc_type)
    for doc in all_docs:
        if run_id in doc.pay_run_ids:
            return doc
    return None
