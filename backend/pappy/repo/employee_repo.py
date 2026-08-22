"""Employee repo — PK=`EMPLOYER#<id>`, SK=`EMPLOYEE#<empId>`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Key

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.employee import Employee
from pappy.repo import keys
from pappy.repo.exceptions import NotFoundError


def _to_item(employee: Employee) -> dict[str, Any]:
    item = employee.model_dump(mode="json")
    item["pk"] = keys.employer_pk(employee.employer_id)
    item["sk"] = keys.employee_sk(employee.employee_id)
    return item


def _from_item(item: dict[str, Any]) -> Employee:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return Employee.model_validate(body)


def put(table: Table, employee: Employee) -> Employee:
    table.put_item(Item=_to_item(employee))
    return employee


def get(table: Table, employer_id: str, employee_id: str) -> Employee:
    response = table.get_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.employee_sk(employee_id)}
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("Employee", employee_id)
    return _from_item(item)


def get_or_none(table: Table, employer_id: str, employee_id: str) -> Employee | None:
    response = table.get_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.employee_sk(employee_id)}
    )
    item = response.get("Item")
    return None if item is None else _from_item(item)


def list_for_employer(table: Table, employer_id: str) -> list[Employee]:
    response = table.query(
        KeyConditionExpression=Key("pk").eq(keys.employer_pk(employer_id))
        & Key("sk").begins_with(keys.employee_sk_prefix())
    )
    return [_from_item(item) for item in response.get("Items", [])]


def delete(table: Table, employer_id: str, employee_id: str) -> None:
    table.delete_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.employee_sk(employee_id)}
    )
