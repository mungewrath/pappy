"""Dependent care FSA receipts (design-doc.md §6.3).

Covers the three claims the design makes about this feature, plus the PII rule
it has to respect:

- the amount is the sum of gross wages for finalized runs in the service
  range, with employer FICA only when the employer opts in;
- cumulative claimed is tracked across receipts and the plan limit warns
  before an over-claim;
- the provider TIN feeds one generated PDF and is never written down (§7.3).

The provider TIN is asserted absent from the *DynamoDB item* as well as the
response, because a leaked TIN in a persisted record is the failure mode §7.3
actually cares about — it would outlive the request that supplied it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table
from pypdf import PdfReader

from pappy.documents.fsa_receipt import generate_fsa_receipt_pdf
from pappy.models.common import Address
from pappy.models.document import DocumentType
from pappy.models.employee import DefaultScheduleLine, Employee, EmployeeCreate
from pappy.models.employer import Employer, EmployerCreate, EmployerUpdate
from pappy.models.ratetable import RateTable, parse_rate_table
from pappy.models.w4 import W4Election
from pappy.money import Money
from pappy.repo import document_repo, employee_repo, employer_repo, keys, rate_table_repo
from pappy.repo.bucket import get_bucket
from pappy.services import employee_service, employer_service, fsa_service, payrun_service

# The API derives `employerId` from the JWT `sub` claim (§7.1), and the
# `client` fixture authenticates as `DEFAULT_SUB`. Seeding a household under a
# different id would make every seeded row invisible to the API tests, so the
# employer id *is* the sub throughout this module.
from tests.conftest import DEFAULT_SUB

EMPLOYER_ID = DEFAULT_SUB
EMPLOYEE_ID = "nanny-1"
TIN = "123-45-6789"
DEPENDENT = "Kid Smith"

WEEKLY_GROSS = Money("1187.50")
STATUTORY_LIMIT = Money("5000.00")


@pytest.fixture
def local_documents_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "documents"
    monkeypatch.setenv("PAPPY_DOCUMENTS_DIR", str(directory))
    monkeypatch.delenv("PAPPY_DOCUMENTS_BUCKET_NAME", raising=False)
    return directory


def _seed(table: Table, *, include_employer_taxes: bool = False, plan_limit: str | None = None) -> None:
    employer_repo.put(
        table,
        Employer.new(
            employer_id=EMPLOYER_ID,
            data=EmployerCreate(
                legal_name="Jane Doe",
                ein="12-3456789",
                address=Address(
                    line1="1 Main St", city="Seattle", state="WA", zip_code="98101"
                ),
                fsa_include_employer_taxes=include_employer_taxes,
                fsa_plan_limit=Money(plan_limit) if plan_limit else None,
            ),
        ),
    )
    employee_repo.put(
        table,
        Employee.new(
            employer_id=EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            data=EmployeeCreate(
                full_name="Nanny Smith",
                address=Address(
                    line1="2 Elm St", city="Seattle", state="WA", zip_code="98102"
                ),
                hire_date=date(2026, 1, 1),
                hourly_rate=Decimal("25.00"),
                default_schedule=[
                    DefaultScheduleLine(weekday=weekday, hours=Decimal(9))
                    for weekday in range(5)
                ],
            ),
        ),
    )
    employee_service.add_w4_election(
        table, EMPLOYER_ID, EMPLOYEE_ID, W4Election(effective_date=date(2025, 1, 1))
    )


def _finalize_week(table: Table, pay_date: date) -> str:
    from pappy.models.payrun import PayRunCreate

    draft = payrun_service.create_draft(
        table,
        EMPLOYER_ID,
        EMPLOYEE_ID,
        PayRunCreate(
            period_start=pay_date - timedelta(days=11),
            period_end=pay_date - timedelta(days=5),
            pay_date=pay_date,
        ),
    )
    return payrun_service.finalize_run(table, EMPLOYER_ID, draft.run_id).run_id


def _pdf_text(pdf_bytes: bytes) -> str:
    """All text in a PDF, pages joined.

    `extract_text` is a page method, not a reader method — joining every page
    keeps assertions from caring whether content spilled onto a second one.
    """
    return "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(pdf_bytes)).pages)


class TestGenerator:
    def _bytes(self, **overrides: str | int | None) -> bytes:
        kwargs: dict[str, str | int | None] = {
            "employer_name": "Jane Doe",
            "employer_address_line1": "1 Main St",
            "employer_address_city": "Seattle",
            "employer_address_state": "WA",
            "employer_address_zip": "98101",
            "provider_name": "Nanny Smith",
            "provider_tin": TIN,
            "provider_address_line1": "2 Elm St",
            "provider_address_city": "Seattle",
            "provider_address_state": "WA",
            "provider_address_zip": "98102",
            "dependent_name": DEPENDENT,
            "service_start": "2026-01-01",
            "service_end": "2026-03-31",
            "amount_paid": "3562.50",
            "wage_basis_note": "Amount derived from gross wages paid.",
            "tax_year": 2026,
        }
        kwargs.update(overrides)
        return generate_fsa_receipt_pdf(**kwargs)  # type: ignore[arg-type]

    def test_returns_a_readable_pdf(self) -> None:
        assert self._bytes().startswith(b"%PDF")

    @pytest.mark.parametrize(
        "expected",
        [
            "Dependent Care FSA Receipt",
            "Nanny Smith",
            TIN,
            "Kid Smith",
            "2026-01-01",
            "2026-03-31",
            "$3,562.50",
            "Statement of services",
            "Signature of care provider",
            "Amount derived from gross wages paid.",
        ],
    )
    def test_required_content_is_present(self, expected: str) -> None:
        # §6.3 requires provider name, address, TIN, dates of service, amount
        # paid, and the dependent's name — plus a statement and signature block.
        assert expected in _pdf_text(self._bytes())

    def test_address_lines_are_rendered(self) -> None:
        text = _pdf_text(self._bytes())
        assert "2 Elm St" in text
        assert "Seattle, WA 98102" in text

    def test_tax_year_row_is_optional(self) -> None:
        without = _pdf_text(self._bytes(tax_year=None))
        # An empty tax year is dropped rather than rendered as a blank row.
        assert "Tax year" not in without


class TestFsaFigures:
    def test_eligible_amount_is_the_sum_of_gross_wages(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        for pay_date in (date(2026, 1, 16), date(2026, 1, 23), date(2026, 1, 30)):
            _finalize_week(dynamodb_table, pay_date)

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert figures.pay_run_count == 3
        assert figures.gross_wages == Money("3562.50")
        assert figures.claim_amount == Money("3562.50")

    def test_employer_taxes_are_excluded_by_default(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert figures.employer_fica.amount > 0
        assert figures.eligible_wages == figures.gross_wages

    def test_employer_fica_is_added_when_opted_in(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table, include_employer_taxes=True)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert figures.eligible_wages == figures.gross_wages + figures.employer_fica

    def test_drafts_are_not_claimable(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        from pappy.models.payrun import PayRunCreate

        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        payrun_service.create_draft(
            dynamodb_table,
            EMPLOYER_ID,
            EMPLOYEE_ID,
            PayRunCreate(
                period_start=date(2026, 2, 1),
                period_end=date(2026, 2, 7),
                pay_date=date(2026, 2, 13),
            ),
        )

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 2, 28),
        )
        # A draft's wages are not yet owed and may still change.
        assert figures.pay_run_count == 1

    def test_claim_amount_can_be_less_than_the_eligible_total(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        for pay_date in (date(2026, 1, 16), date(2026, 1, 23)):
            _finalize_week(dynamodb_table, pay_date)

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            claim_amount=Money("500.00"),
        )
        assert figures.eligible_wages == Money("2375.00")
        assert figures.claim_amount == Money("500.00")

    def test_reversed_period_is_rejected(self, dynamodb_table: Table) -> None:
        _seed(dynamodb_table)
        with pytest.raises(ValueError, match="period_start must not be after period_end"):
            fsa_service.fsa_figures(
                dynamodb_table,
                EMPLOYER_ID,
                employee_id=EMPLOYEE_ID,
                period_start=date(2026, 3, 31),
                period_end=date(2026, 1, 1),
            )

    def test_negative_claim_is_rejected(self, dynamodb_table: Table) -> None:
        _seed(dynamodb_table)
        with pytest.raises(ValueError, match="claim_amount cannot be negative"):
            fsa_service.fsa_figures(
                dynamodb_table,
                EMPLOYER_ID,
                employee_id=EMPLOYEE_ID,
                period_start=date(2026, 1, 1),
                period_end=date(2026, 1, 31),
                claim_amount=Money("-1.00"),
            )


class TestPlanLimit:
    def test_statutory_limit_comes_from_the_rate_table(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert figures.plan_limit == STATUTORY_LIMIT
        assert figures.limit_source == "statutory"

    def test_plan_limit_overrides_the_statutory_cap(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table, plan_limit="2000.00")
        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert figures.plan_limit == Money("2000.00")
        assert figures.limit_source == "plan"

    def test_a_claim_within_the_limit_does_not_warn(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
        )

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            claim_amount=Money("1000.00"),
        )
        assert figures.already_claimed == WEEKLY_GROSS
        assert figures.over_limit is False
        assert figures.warning is None
        assert figures.remaining_before_claim == STATUTORY_LIMIT - WEEKLY_GROSS

    def test_a_claim_over_the_limit_warns(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table, plan_limit="2000.00")
        fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
            claim_amount=Money("1800.00"),
        )

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            claim_amount=Money("500.00"),
        )
        assert figures.already_claimed == Money("1800.00")
        assert figures.over_limit is True
        assert figures.warning is not None
        assert "2300.00" in figures.warning
        assert "2000.00" in figures.warning

    def test_claiming_exactly_to_the_limit_is_not_over(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table, plan_limit="2000.00")
        fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
            claim_amount=Money("1500.00"),
        )

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 2, 1),
            period_end=date(2026, 2, 28),
            claim_amount=Money("500.00"),
        )
        assert figures.over_limit is False

    def test_cumulative_claimed_accumulates_across_receipts(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table, plan_limit="10000.00")
        for month, amount in ((1, "1000.00"), (2, "1500.00"), (3, "250.00")):
            fsa_service.generate_receipt(
                dynamodb_table,
                EMPLOYER_ID,
                employee_id=EMPLOYEE_ID,
                period_start=date(2026, month, 1),
                period_end=date(2026, month, 28),
                dependent_name=DEPENDENT,
                provider_tin=TIN,
                claim_amount=Money(amount),
            )

        # Derived from the receipts on file, so it cannot drift from what was
        # actually issued.
        assert fsa_service.already_claimed(dynamodb_table, EMPLOYER_ID, 2026) == Money(
            "2750.00"
        )

    def test_other_document_types_do_not_count_as_claims(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        # A pay stub carries no claimed_amount, so it must not be summed in.
        fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
            claim_amount=Money("500.00"),
        )
        from pappy.models.document import Document

        document_repo.put(
            dynamodb_table,
            Document.new(
                employer_id=EMPLOYER_ID,
                document_type=DocumentType.PAY_STUB,
                tax_year=2026,
                s3_key=f"{EMPLOYER_ID}/pay-stubs/x.pdf",
                sha256="0" * 64,
            ),
        )

        assert fsa_service.already_claimed(dynamodb_table, EMPLOYER_ID, 2026) == Money(
            "500.00"
        )

    def test_claims_are_scoped_to_the_tax_year(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table, plan_limit="10000.00")
        fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
            claim_amount=Money("500.00"),
        )
        assert fsa_service.already_claimed(dynamodb_table, EMPLOYER_ID, 2025) == Money.zero


class TestGenerateReceipt:
    def test_stores_a_hashed_receipt_document(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        doc, figures = fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
        )
        assert doc.document_type == DocumentType.FSA_RECEIPT
        assert doc.tax_year == 2026
        assert doc.period_start == date(2026, 1, 1)
        assert doc.period_end == date(2026, 1, 31)
        assert doc.claimed_amount == figures.claim_amount
        assert doc.filename.endswith(".pdf")

        stored = get_bucket().local_path(doc.s3_key).read_bytes()
        assert hashlib.sha256(stored).hexdigest() == doc.sha256
        assert stored.startswith(b"%PDF")

    def test_receipt_pdf_carries_the_claim_details(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        doc, _figures = fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
        )
        text = _pdf_text(get_bucket().local_path(doc.s3_key).read_bytes())
        for expected in ("Nanny Smith", TIN, DEPENDENT, "2026-01-01", "2026-01-31", "$1,187.50"):
            assert expected in text

    def test_provider_tin_is_never_persisted(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        """§7.3: the TIN feeds one PDF and is written down nowhere else.

        Checked against every item in the table, not just the receipt — a
        persisted TIN would outlive the request that supplied it.
        """
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        doc, _figures = fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
        )
        # The PDF does contain the TIN — that is the point of the receipt.
        # (Checked as extracted text: reportlab encodes glyphs into content
        # streams, so the literal string is not in the raw bytes.)
        assert TIN in _pdf_text(get_bucket().local_path(doc.s3_key).read_bytes())

        scanned = dynamodb_table.scan()
        assert scanned["Count"] > 0
        for item in scanned["Items"]:
            assert TIN not in repr(item)

    def test_wage_basis_note_reflects_the_employer_toggle(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table, include_employer_taxes=True)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        doc, _figures = fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
        )
        text = _pdf_text(get_bucket().local_path(doc.s3_key).read_bytes())
        assert "Social Security and Medicare" in text

    def test_over_limit_receipt_is_still_generated_with_a_warning(
        self, dynamodb_table: Table, seeded_rates: RateTable, local_documents_dir: Path
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table, plan_limit="100.00")
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        doc, figures = fsa_service.generate_receipt(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            dependent_name=DEPENDENT,
            provider_tin=TIN,
        )
        # The paperwork is produced either way — the employer's remedy is to
        # submit a smaller claim, not to have the app refuse (§6.3).
        assert figures.over_limit is True
        assert figures.warning is not None
        assert document_repo.get_by_id(dynamodb_table, EMPLOYER_ID, doc.doc_id) == doc


class TestEmployerFsaConfig:
    def test_plan_limit_round_trips_through_a_patch(
        self, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table)
        updated = employer_service.update_employer(
            dynamodb_table,
            EMPLOYER_ID,
            EmployerUpdate(
                fsa_plan_limit=Money("3000.00"), fsa_include_employer_taxes=True
            ),
        )
        assert updated.fsa_plan_limit == Money("3000.00")
        assert updated.fsa_include_employer_taxes is True

    def test_patching_one_field_leaves_the_other_alone(
        self, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table, include_employer_taxes=True)
        updated = employer_service.update_employer(
            dynamodb_table, EMPLOYER_ID, EmployerUpdate(ubi="123-45-678-90")
        )
        assert updated.fsa_include_employer_taxes is True
        assert updated.fsa_plan_limit is None


class TestFsaApi:
    def test_preview_returns_figures_without_writing(
        self, client: TestClient, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        response = client.get(
            "/fsa/preview",
            params={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["eligible_wages"] == "1187.50"
        assert body["claim_amount"] == "1187.50"
        assert body["plan_limit"] == "5000.00"
        assert body["over_limit"] is False
        assert body["warning"] is None
        assert document_repo.list_for_employer(dynamodb_table, EMPLOYER_ID) == []

    def test_preview_accepts_a_claim_override(
        self, client: TestClient, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        response = client.get(
            "/fsa/preview",
            params={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "claim_amount": "250.00",
            },
        )
        assert response.status_code == 200
        assert response.json()["claim_amount"] == "250.00"

    def test_create_receipt_stores_and_returns_the_document(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        response = client.post(
            "/fsa/receipts",
            json={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "dependent_name": DEPENDENT,
                "provider_tin": TIN,
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["document"]["document_type"] == "FSA_RECEIPT"
        assert body["document"]["claimed_amount"] == "1187.50"
        assert body["figures"]["claim_amount"] == "1187.50"

    def test_receipt_appears_in_the_document_archive(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        client.post(
            "/fsa/receipts",
            json={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "dependent_name": DEPENDENT,
                "provider_tin": TIN,
            },
        )

        listed = client.get("/documents", params={"doc_type": "FSA_RECEIPT"}).json()
        assert len(listed) == 1
        assert listed[0]["period_start"] == "2026-01-01"

    def test_download_is_served_as_a_pdf(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        """The local transport serves the stored bytes with a real PDF type."""
        del local_documents_dir
        _seed(dynamodb_table)
        created = client.post(
            "/fsa/receipts",
            json={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "dependent_name": DEPENDENT,
                "provider_tin": TIN,
            },
        ).json()

        content = client.get(f"/documents/{created['document']['doc_id']}/content")
        assert content.status_code == 200
        assert content.headers["content-type"].startswith("application/pdf")

    def test_empty_dependent_name_is_rejected(
        self, client: TestClient, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table)
        response = client.post(
            "/fsa/receipts",
            json={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "dependent_name": "",
                "provider_tin": TIN,
            },
        )
        assert response.status_code == 422

    def test_empty_tin_is_rejected(self, client: TestClient, dynamodb_table: Table) -> None:
        _seed(dynamodb_table)
        response = client.post(
            "/fsa/receipts",
            json={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "dependent_name": DEPENDENT,
                "provider_tin": "",
            },
        )
        assert response.status_code == 422

    def test_receipt_is_scoped_to_the_callers_employer(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        auth_headers: Callable[[str], dict[str, str]],
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        client.post(
            "/fsa/receipts",
            json={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
                "dependent_name": DEPENDENT,
                "provider_tin": TIN,
            },
        )

        other = client.get(
            "/fsa/preview",
            params={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
            headers=auth_headers("someone-else"),
        )
        # A claim needs the employer's FSA config, and `someone-else` has no
        # employer profile — so the lookup 404s before any of the seeded claim
        # or wage data is reachable. That is the isolation guarantee (§7.1).
        assert other.status_code == 404


class TestYearViewApi:
    def test_year_view_endpoint_returns_rows(
        self, client: TestClient, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        _finalize_week(dynamodb_table, date(2026, 1, 23))

        response = client.get("/tax-years/2026/year-view")
        assert response.status_code == 200
        body = response.json()
        assert body["tax_year"] == 2026
        assert len(body["rows"]) == 2
        assert body["totals"]["finalized_run_count"] == 2
        assert body["totals"]["gross"] == "2375.00"
        assert body["rows"][0]["ytd_gross"] == "1187.50"
        assert body["rows"][1]["ytd_gross"] == "2375.00"

    def test_year_view_honours_the_date_range(
        self, client: TestClient, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        _seed(dynamodb_table)
        for pay_date in (date(2026, 1, 16), date(2026, 1, 23), date(2026, 1, 30)):
            _finalize_week(dynamodb_table, pay_date)

        response = client.get(
            "/tax-years/2026/year-view",
            params={"start": "2026-01-16", "end": "2026-01-23"},
        )
        assert response.status_code == 200
        body = response.json()
        assert [row["pay_date"] for row in body["rows"]] == ["2026-01-16", "2026-01-23"]
        assert body["period_start"] == "2026-01-16"

    def test_export_endpoint_returns_a_document(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        response = client.post("/tax-years/2026/year-view.csv")
        assert response.status_code == 201
        body = response.json()
        assert body["document_type"] == "YEAR_VIEW_CSV"
        assert body["filename"].endswith(".csv")

    def test_exported_csv_is_served_as_text_csv(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        """Regression: the local transport used to hardcode `application/pdf`,
        which would hand a CSV to the browser as a broken document."""
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        doc_id = client.post("/tax-years/2026/year-view.csv").json()["doc_id"]

        content = client.get(f"/documents/{doc_id}/content")
        assert content.status_code == 200
        assert content.headers["content-type"].startswith("text/csv")
        assert content.text.startswith("Pay date,Period start")

    def test_exported_csv_hash_matches_the_served_bytes(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        local_documents_dir: Path,
    ) -> None:
        del local_documents_dir
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))
        doc = client.post("/tax-years/2026/year-view.csv").json()

        content = client.get(f"/documents/{doc['doc_id']}/content")
        assert hashlib.sha256(content.content).hexdigest() == doc["sha256"]
        assert content.headers["X-Content-SHA256"] == doc["sha256"]

    def test_year_view_is_scoped_to_the_callers_employer(
        self,
        client: TestClient,
        dynamodb_table: Table,
        seeded_rates: RateTable,
        auth_headers: Callable[[str], dict[str, str]],
    ) -> None:
        _seed(dynamodb_table)
        _finalize_week(dynamodb_table, date(2026, 1, 16))

        response = client.get(
            "/tax-years/2026/year-view", headers=auth_headers("someone-else")
        )
        assert response.status_code == 200
        assert response.json()["rows"] == []


class TestFsaReceiptInS3:
    def test_receipt_uploads_to_s3_when_a_bucket_is_configured(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        """The deployed transport stores bytes in S3 with a content type."""
        import boto3

        with mock_aws():
            os.environ["PAPPY_DOCUMENTS_BUCKET_NAME"] = "test-fsa-bucket"
            try:
                client = boto3.client("s3", region_name="us-west-2")
                client.create_bucket(
                    Bucket="test-fsa-bucket",
                    CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
                )
                _seed(dynamodb_table)
                doc, _figures = fsa_service.generate_receipt(
                    dynamodb_table,
                    EMPLOYER_ID,
                    employee_id=EMPLOYEE_ID,
                    period_start=date(2026, 1, 1),
                    period_end=date(2026, 1, 31),
                    dependent_name=DEPENDENT,
                    provider_tin=TIN,
                    claim_amount=Money("100.00"),
                )
                head = client.head_object(Bucket="test-fsa-bucket", Key=doc.s3_key)
                assert head["ContentType"] == "application/pdf"
            finally:
                del os.environ["PAPPY_DOCUMENTS_BUCKET_NAME"]


class TestPreChangeRateTable:
    """Regression: a rate-table row written before `dependent_care_fsa` existed.

    §5.2 makes rate-table versions immutable, and `put_if_absent` refuses to
    overwrite one a finalized run references. So a row seeded by an earlier
    release stays in the table forever without the new block, and every read
    re-validates it. When the block was a *required* field, that turned into an
    unhandled `ValidationError` and a 500 on both the earnings summary and the
    FSA preview. The field is optional for exactly this reason, and a version
    bump is what installs the data going forward.
    """

    def _store_legacy_row(self, table: Table) -> None:
        """Write a v1 row in the exact shape an earlier release produced.

        Same field set and sort key as the real seeder writes, minus the block
        that did not exist then.
        """
        raw = json.loads(
            (Path(__file__).resolve().parents[2] / "rates" / "2026.json").read_text()
        )
        raw.pop("dependent_care_fsa")
        body = {**raw, "version": 1}
        table.put_item(
            Item={"pk": keys.rates_pk(2026), "sk": keys.rates_version_sk(1), **body}
        )

    def test_legacy_row_still_parses(self, dynamodb_table: Table) -> None:
        self._store_legacy_row(dynamodb_table)
        legacy = rate_table_repo.latest_for_year(dynamodb_table, 2026)
        assert legacy is not None
        assert legacy.dependent_care_fsa is None

    def test_latest_prefers_the_version_that_carries_the_block(
        self, dynamodb_table: Table, seeded_rates: RateTable
    ) -> None:
        # `seeded_rates` installs the current file (v2, with the block) alongside
        # the pre-change v1 row, which is exactly a mid-deployment state.
        assert seeded_rates.version == 2
        self._store_legacy_row(dynamodb_table)

        latest = rate_table_repo.latest_for_year(dynamodb_table, 2026)
        assert latest is not None
        assert latest.version == 2
        assert latest.dependent_care_fsa is not None
        assert latest.dependent_care_fsa.annual_limit == STATUTORY_LIMIT

    def test_payroll_numbers_are_unchanged_by_the_version_bump(self) -> None:
        """v2 differs from v1 only by the added block, so withholding must match."""
        raw = json.loads(
            (Path(__file__).resolve().parents[2] / "rates" / "2026.json").read_text()
        )
        v2 = parse_rate_table(raw)
        v1 = parse_rate_table({k: v for k, v in raw.items() if k != "dependent_care_fsa"})

        assert v2.version == 1 + 1  # bumped, so the new block actually installs
        assert v2.federal_income_tax == v1.federal_income_tax
        assert v2.social_security == v1.social_security
        assert v2.medicare == v1.medicare
        assert v2.futa == v1.futa
        assert v2.wa_pfml == v1.wa_pfml
        assert v2.wa_cares == v1.wa_cares
        assert v2.wa_ui == v1.wa_ui
        assert v2.household_coverage == v1.household_coverage

    def test_unknown_limit_disables_the_check_without_blocking(
        self, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table)
        self._store_legacy_row(dynamodb_table)

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            claim_amount=Money("999999.00"),
        )
        # No cap could be established, so none is applied — claiming still works.
        assert figures.limit_source == "unknown"
        assert figures.over_limit is False
        assert figures.warning is None

    def test_plan_limit_still_wins_over_an_unknown_statutory_cap(
        self, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table, plan_limit="2000.00")
        self._store_legacy_row(dynamodb_table)

        figures = fsa_service.fsa_figures(
            dynamodb_table,
            EMPLOYER_ID,
            employee_id=EMPLOYEE_ID,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
        )
        assert figures.limit_source == "plan"
        assert figures.plan_limit == Money("2000.00")

    def test_earnings_summary_does_not_500_on_a_legacy_row(
        self, client: TestClient, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table)
        self._store_legacy_row(dynamodb_table)

        response = client.get("/tax-years/2026/earnings-summary")
        assert response.status_code == 200

    def test_fsa_preview_does_not_500_on_a_legacy_row(
        self, client: TestClient, dynamodb_table: Table
    ) -> None:
        _seed(dynamodb_table)
        self._store_legacy_row(dynamodb_table)

        response = client.get(
            "/fsa/preview",
            params={
                "employee_id": EMPLOYEE_ID,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )
        assert response.status_code == 200
        assert response.json()["limit_source"] == "unknown"

    def test_finalize_still_works_against_a_legacy_only_table(
        self, dynamodb_table: Table
    ) -> None:
        """A deployment holding only v1 must still be able to run payroll."""
        _seed(dynamodb_table)
        self._store_legacy_row(dynamodb_table)

        run_id = _finalize_week(dynamodb_table, date(2026, 1, 16))
        assert run_id
