"""YTD accumulator repo — SK=`YTD#<taxYear>#<empId>` (design-doc.md §4).

Wage-base caps must be correct without re-reading the year's runs, so the
accumulator is advanced **transactionally** at finalization: the `ADD`-based
update built by `transact_update_item` executes in the same
`TransactWriteItems` as the finalized run's write (see
`pappy.repo.payrun_repo.finalize`). ADD is atomic under transaction
isolation, so two runs finalizing concurrently cannot lose an increment.

Unlike Money values on documents (stored as decimal strings, §5.5), the
wage attributes here are stored as DynamoDB *numbers*: ADD only works on the
`N` type. These are internal accumulator quantities, never rendered, and the
boto3 resource layer deserializes them straight back to `Decimal`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.types import TypeSerializer

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef

from pappy.models.ytd import YtdAccumulator
from pappy.repo import keys

_SERIALIZER = TypeSerializer()

# Wage attributes advanced by ADD on each finalized run.
_WAGE_FIELDS = (
    "social_security_wages",
    "medicare_wages",
    "futa_wages",
    "wa_ui_wages",
    "wa_pfml_wages",
)


def get_or_none(
    table: Table, employer_id: str, employee_id: str, tax_year: int
) -> YtdAccumulator | None:
    response = table.get_item(
        Key={
            "pk": keys.employer_pk(employer_id),
            "sk": keys.ytd_sk(tax_year, employee_id),
        }
    )
    item = response.get("Item")
    if item is None:
        return None
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return YtdAccumulator.model_validate(body)


def transact_update_item(
    table: Table,
    employer_id: str,
    employee_id: str,
    tax_year: int,
    delta: YtdAccumulator,
) -> TransactWriteItemTypeDef:
    """The low-level `Update` operation advancing the accumulator by `delta`.

    `delta` carries this run's capped wage slices in its wage fields. Identity
    fields are SET unconditionally; wages are ADDed (implicit 0 when absent),
    which both creates the item on first finalize and increments thereafter.
    """
    now = datetime.now(UTC).isoformat()
    adds = ", ".join(f"#{field} :{field}" for field in _WAGE_FIELDS)
    values: dict[str, Any] = {
        f":{field}": _SERIALIZER.serialize(getattr(delta, field)) for field in _WAGE_FIELDS
    }
    values[":er"] = _SERIALIZER.serialize(employer_id)
    values[":emp"] = _SERIALIZER.serialize(employee_id)
    values[":ty"] = _SERIALIZER.serialize(Decimal(tax_year))
    values[":ts"] = _SERIALIZER.serialize(now)
    return {
        "Update": {
            "TableName": table.name,
            "Key": {
                "pk": _SERIALIZER.serialize(keys.employer_pk(employer_id)),
                "sk": _SERIALIZER.serialize(keys.ytd_sk(tax_year, employee_id)),
            },
            # Attribute names are placeholdered wholesale — DynamoDB's
            # reserved-word list is large and grows, and an update expression
            # is the wrong place to discover a collision.
            "UpdateExpression": (
                f"ADD {adds} "
                "SET employer_id = :er, employee_id = :emp, #tax_year = :ty, "
                "created_at = if_not_exists(created_at, :ts), updated_at = :ts"
            ),
            "ExpressionAttributeNames": {
                "#tax_year": "tax_year",
                **{f"#{field}": field for field in _WAGE_FIELDS},
            },
            "ExpressionAttributeValues": values,
        }
    }
