from datetime import UTC, datetime
from decimal import Decimal

from mypy_boto3_dynamodb.service_resource import Table

from pappy.calc.payroll import TaxableWages
from pappy.models.ytd import YtdAccumulator
from pappy.repo import ytd_repo


def _accumulator(
    *,
    social_security_wages: Decimal = Decimal(0),
    medicare_wages: Decimal = Decimal(0),
    futa_wages: Decimal = Decimal(0),
    wa_ui_wages: Decimal = Decimal(0),
    wa_pfml_wages: Decimal = Decimal(0),
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> YtdAccumulator:
    return YtdAccumulator(
        employer_id="emp-1",
        employee_id="nanny-1",
        tax_year=2026,
        social_security_wages=social_security_wages,
        medicare_wages=medicare_wages,
        futa_wages=futa_wages,
        wa_ui_wages=wa_ui_wages,
        wa_pfml_wages=wa_pfml_wages,
        created_at=created_at,
        updated_at=updated_at,
    )


def test_get_or_none_returns_none_before_first_finalize(dynamodb_table: Table) -> None:
    assert ytd_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1", 2026) is None


def test_transact_update_item_shape(dynamodb_table: Table) -> None:
    delta = _accumulator(social_security_wages=Decimal("1187.50"))
    op = ytd_repo.transact_update_item(dynamodb_table, "emp-1", "nanny-1", 2026, delta)

    assert set(op) == {"Update"}
    update = op["Update"]
    assert update["TableName"] == dynamodb_table.name
    assert update["Key"]["sk"] == {"S": "YTD#2026#nanny-1"}
    assert "ADD" in update["UpdateExpression"]
    assert "if_not_exists(created_at" in update["UpdateExpression"]
    # wage deltas serialize as DynamoDB numbers so ADD is atomic on N types
    assert update["ExpressionAttributeValues"][":social_security_wages"] == {"N": "1187.50"}


def test_round_trip_preserves_decimals_and_timestamps(dynamodb_table: Table) -> None:
    stored = _accumulator(
        social_security_wages=Decimal("12345.67"),
        medicare_wages=Decimal("12345.67"),
        futa_wages=Decimal(7000),
        wa_ui_wages=Decimal("5000.25"),
        wa_pfml_wages=Decimal("9999.99"),
        created_at=datetime(2026, 1, 9, tzinfo=UTC),
        updated_at=datetime(2026, 3, 13, tzinfo=UTC),
    )
    dynamodb_table.put_item(
        Item={
            "pk": "EMPLOYER#emp-1",
            "sk": "YTD#2026#nanny-1",
            **stored.model_dump(mode="json"),
        }
    )

    fetched = ytd_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1", 2026)
    assert fetched == stored


def test_apply_taxable_mirrors_add_semantics() -> None:
    base = _accumulator(futa_wages=Decimal(7000))
    taxable = TaxableWages(
        social_security=Decimal(1000),
        medicare=Decimal(1000),
        additional_medicare=Decimal(0),
        futa=Decimal(0),
        wa_ui=Decimal(1000),
        wa_pfml=Decimal(1000),
    )

    updated = base.apply_taxable(taxable)

    assert updated.futa_wages == Decimal(7000)  # capped slice of zero adds nothing
    assert updated.social_security_wages == Decimal(1000)
    # pure — the input accumulator is untouched
    assert base.futa_wages == Decimal(7000)
