"""W-4 election repo — SK=`EMPLOYEE#<empId>#W4#<effectiveDate>` (§4).

Elections are effective-dated children of the employee (design-doc.md §3.1,
§5.3 "Mid-year W-4 changes"): a re-election adds a new item rather than
rewriting history, and a pay run resolves the election in effect on its pay
date via `pappy.calc.fit.resolve_w4`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Key

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.w4 import W4Election
from pappy.repo import keys
from pappy.repo.exceptions import NotFoundError


def _to_item(employer_id: str, employee_id: str, election: W4Election) -> dict[str, Any]:
    item = election.model_dump(mode="json")
    item["pk"] = keys.employer_pk(employer_id)
    item["sk"] = keys.w4_sk(employee_id, election.effective_date)
    return item


def _from_item(item: dict[str, Any]) -> W4Election:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return W4Election.model_validate(body)


def put(
    table: Table, employer_id: str, employee_id: str, election: W4Election
) -> W4Election:
    """Store one election. Re-submitting the same effective date replaces it
    (a same-day correction); a new effective date never touches earlier rows."""
    table.put_item(Item=_to_item(employer_id, employee_id, election))
    return election


def get(table: Table, employer_id: str, employee_id: str, effective_date: str) -> W4Election:
    response = table.get_item(
        Key={
            "pk": keys.employer_pk(employer_id),
            "sk": f"{keys.w4_sk_prefix(employee_id)}{effective_date}",
        }
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("W4Election", f"{employee_id}@{effective_date}")
    return _from_item(item)


def list_for_employee(table: Table, employer_id: str, employee_id: str) -> list[W4Election]:
    """All elections for one employee, ascending by effective date."""
    response = table.query(
        KeyConditionExpression=Key("pk").eq(keys.employer_pk(employer_id))
        & Key("sk").begins_with(keys.w4_sk_prefix(employee_id))
    )
    elections = [_from_item(item) for item in response.get("Items", [])]
    return sorted(elections, key=lambda e: e.effective_date)
