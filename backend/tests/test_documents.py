"""Phase 3 document store and pay stub integration tests."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

import boto3
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table
from pypdf import PdfReader

from pappy.documents.pay_stub import generate_pay_stub_pdf
from pappy.models.document import Document, DocumentType
from pappy.repo import document_repo

BUCKET_NAME = "test-pappy-documents"


@pytest.fixture(autouse=True)
def _set_bucket_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPPY_DOCUMENTS_BUCKET_NAME", BUCKET_NAME)


@pytest.fixture
def s3_bucket() -> Any:
    with mock_aws():
        s3 = boto3.client("s3", region_name="us-west-2")
        s3.create_bucket(
            Bucket=BUCKET_NAME,
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        yield s3


def _document(*, tax_year: int = 2026, doc_type: DocumentType = DocumentType.PAY_STUB) -> Document:
    return Document.new(
        employer_id="emp-1",
        document_type=doc_type,
        tax_year=tax_year,
        s3_key=f"emp-1/documents/{tax_year}/{doc_type.value}.pdf",
        sha256="abc123",
        filename=f"{doc_type.value.lower()}.pdf",
        pay_run_ids=["run-1"],
    )


def _pdf_bytes() -> bytes:
    return generate_pay_stub_pdf(
        employer_name="Jane Doe",
        employer_ein="12-3456789",
        employer_address_line1="1 Main St",
        employer_address_line2="Unit 4",
        employer_address_city="Seattle",
        employer_address_state="WA",
        employer_address_zip="98101",
        employee_name="Nanny Smith",
        employee_address_line1="2 Elm St",
        employee_address_line2=None,
        employee_address_city="Seattle",
        employee_address_state="WA",
        employee_address_zip="98102",
        employee_hire_date="2026-01-01",
        period_start="2026-01-05",
        period_end="2026-01-11",
        pay_date="2026-01-16",
        regular_hours="45",
        overtime_hours="5",
        other_paid_hours="0",
        unpaid_hours="0",
        hourly_rate="25.00",
        effective_overtime_rate="37.50",
        overtime_workweek="2026-01-05 - 2026-01-11",
        straight_time_pay="1125.00",
        overtime_premium_pay="62.50",
        gross="1187.50",
        gross_ytd="2375.00",
        withholding_current={
            "social_security": "73.63",
            "medicare": "17.22",
            "additional_medicare": "0.00",
            "federal_income_tax": "100.58",
            "wa_pfml_employee": "3.72",
            "wa_cares_employee": "2.90",
        },
        withholding_ytd={
            "social_security": "147.26",
            "medicare": "34.44",
            "additional_medicare": "0.00",
            "federal_income_tax": "201.16",
            "wa_pfml_employee": "7.44",
            "wa_cares_employee": "5.80",
        },
        total_withholding_current="198.05",
        total_withholding_ytd="396.10",
        net_pay_current="989.45",
        net_pay_ytd="1978.90",
    )


def _create_employer(client: TestClient) -> None:
    response = client.post(
        "/employers",
        json={
            "legal_name": "Jane Doe",
            "ein": "12-3456789",
            "address": {
                "line1": "1 Main St",
                "line2": "Unit 4",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98101",
            },
        },
    )
    assert response.status_code in (200, 201), response.text


def _create_employee(client: TestClient) -> str:
    response = client.post(
        "/employees",
        json={
            "full_name": "Nanny Smith",
            "address": {
                "line1": "2 Elm St",
                "city": "Seattle",
                "state": "WA",
                "zip_code": "98102",
            },
            "hire_date": "2026-01-01",
            "hourly_rate": "25.00",
            "overtime_policy": "APPLIES",
            "default_schedule": [
                {"weekday": weekday, "hours": "9"} for weekday in range(5)
            ],
        },
    )
    assert response.status_code == 201, response.text
    return str(response.json()["employee_id"])


def _create_run(client: TestClient, employee_id: str, *, finalize: bool) -> str:
    w4 = client.post(
        f"/employees/{employee_id}/w4",
        json={"effective_date": "2026-01-01", "filing_status": "SINGLE_OR_MFS"},
    )
    assert w4.status_code == 201, w4.text
    created = client.post(
        f"/payruns/employees/{employee_id}",
        json={
            "period_start": "2026-01-05",
            "period_end": "2026-01-11",
            "pay_date": "2026-01-16",
        },
    )
    assert created.status_code == 201, created.text
    run_id = str(created.json()["run_id"])
    if finalize:
        finalized = client.post(f"/payruns/{run_id}/finalize", json={})
        assert finalized.status_code == 200, finalized.text
    return run_id


def test_document_model_round_trip() -> None:
    doc = _document()
    assert len(doc.doc_id) == 32
    assert Document.model_validate(doc.model_dump(mode="json")) == doc


def test_document_repo_lookup_and_filters(dynamodb_table: Table) -> None:
    stub = document_repo.put(dynamodb_table, _document())
    document_repo.put(
        dynamodb_table,
        _document(tax_year=2025, doc_type=DocumentType.W2),
    )

    assert document_repo.get_by_id(dynamodb_table, "emp-1", stub.doc_id) == stub
    assert document_repo.get_for_pay_run(
        dynamodb_table, "emp-1", "run-1", DocumentType.PAY_STUB
    ) == stub
    assert document_repo.list_for_employer(
        dynamodb_table, "emp-1", tax_year=2026
    ) == [stub]
    assert document_repo.list_for_employer(
        dynamodb_table, "emp-1", doc_type=DocumentType.W2
    )[0].tax_year == 2025


def test_pay_stub_contains_required_fields() -> None:
    pdf = _pdf_bytes()
    text = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf)).pages)

    assert pdf.startswith(b"%PDF")
    for expected in (
        "Jane Doe",
        "12-3456789",
        "Unit 4",
        "Nanny Smith",
        "2026-01-05",
        "2026-01-11",
        "Overtime premium (0.5x)",
        "effective overtime rate: $37.50",
        "$1,187.50",
        "$2,375.00",
        "Federal Income Tax",
        "$1,978.90",
    ):
        assert expected in text


def test_generate_list_download_and_store_pay_stub(
    client: TestClient, seeded_rates: object, s3_bucket: Any
) -> None:
    _create_employer(client)
    employee_id = _create_employee(client)
    run_id = _create_run(client, employee_id, finalize=True)

    generated = client.post(f"/payruns/{run_id}/pay-stub", json={})
    assert generated.status_code == 201, generated.text
    doc = generated.json()
    assert doc["document_type"] == "PAY_STUB"
    assert doc["pay_run_ids"] == [run_id]
    assert doc["filename"] == "pay-stub-2026-01-16.pdf"

    stored = s3_bucket.get_object(Bucket=BUCKET_NAME, Key=doc["s3_key"])["Body"].read()
    assert stored.startswith(b"%PDF")
    assert hashlib.sha256(stored).hexdigest() == doc["sha256"]

    listed = client.get("/documents?tax_year=2026&doc_type=PAY_STUB")
    assert listed.status_code == 200
    assert listed.json() == [doc]

    download = client.get(f"/documents/{doc['doc_id']}/download")
    assert download.status_code == 200
    assert download.json()["sha256"] == doc["sha256"]
    assert download.json()["filename"] == doc["filename"]
    assert download.json()["expires_in"] == 900
    assert "Signature=" in download.json()["url"]


def test_pay_stub_generation_is_idempotent(
    client: TestClient, seeded_rates: object, s3_bucket: Any
) -> None:
    _create_employer(client)
    run_id = _create_run(client, _create_employee(client), finalize=True)

    first = client.post(f"/payruns/{run_id}/pay-stub", json={})
    second = client.post(f"/payruns/{run_id}/pay-stub", json={})

    assert first.status_code == second.status_code == 201
    assert first.json()["doc_id"] == second.json()["doc_id"]
    assert len(client.get("/documents").json()) == 1


def test_pay_stub_for_draft_is_rejected(
    client: TestClient, seeded_rates: object, s3_bucket: Any
) -> None:
    _create_employer(client)
    run_id = _create_run(client, _create_employee(client), finalize=False)

    response = client.post(f"/payruns/{run_id}/pay-stub", json={})

    assert response.status_code == 409


def test_document_download_is_employer_scoped(
    client: TestClient,
    seeded_rates: object,
    s3_bucket: Any,
    auth_headers: Any,
) -> None:
    _create_employer(client)
    run_id = _create_run(client, _create_employee(client), finalize=True)
    generated = client.post(f"/payruns/{run_id}/pay-stub", json={}).json()

    response = client.get(
        f"/documents/{generated['doc_id']}/download",
        headers=auth_headers("other-employer"),
    )

    assert response.status_code == 404
