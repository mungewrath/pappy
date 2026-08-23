"""Rate table repo — PK=`RATES#<taxYear>`, SK=`VERSION#<n>` (§4, §5.2).

Rate tables are loaded into DynamoDB by a deploy-time seeder and are
**immutable once a pay run references them**: `put_if_absent` refuses to
overwrite an existing version, so correcting a table mid-year means shipping
version n+1 while already-finalized runs keep pointing at version n.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.ratetable import RateTable
from pappy.repo import keys
from pappy.repo.exceptions import AlreadyExistsError, NotFoundError


def _to_item(rate_table: RateTable) -> dict[str, Any]:
    item = rate_table.model_dump(mode="json")
    item["pk"] = keys.rates_pk(rate_table.tax_year)
    item["sk"] = keys.rates_version_sk(rate_table.version)
    return item


def _from_item(item: dict[str, Any]) -> RateTable:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return RateTable.model_validate(body)


def put_if_absent(table: Table, rate_table: RateTable) -> RateTable:
    """Insert a rate-table version; fails if that version already exists.

    Immutability is enforced here rather than trusted to the caller —
    "rates are data, not code" only works if the data cannot be silently
    rewritten under finalized runs (§5.2).
    """
    try:
        table.put_item(
            Item=_to_item(rate_table),
            ConditionExpression=Attr("pk").not_exists() & Attr("sk").not_exists(),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise AlreadyExistsError(
                "RateTable",
                f"{rate_table.tax_year} v{rate_table.version}",
            ) from exc
        raise
    return rate_table


def get(table: Table, tax_year: int, version: int) -> RateTable:
    response = table.get_item(
        Key={"pk": keys.rates_pk(tax_year), "sk": keys.rates_version_sk(version)}
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("RateTable", f"{tax_year} v{version}")
    return _from_item(item)


def latest_for_year(table: Table, tax_year: int) -> RateTable | None:
    """Highest version stored for a tax year, or None if none is seeded."""
    response = table.query(
        KeyConditionExpression=Key("pk").eq(keys.rates_pk(tax_year)),
        ScanIndexForward=False,
        Limit=1,
    )
    items = response.get("Items", [])
    return _from_item(items[0]) if items else None
