"""Employer repo — single item per employer at PK=`EMPLOYER#<id>`, SK=`PROFILE`."""

from __future__ import annotations

from typing import Any

from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.employer import Employer
from pappy.repo import keys
from pappy.repo.exceptions import NotFoundError


def _to_item(employer: Employer) -> dict[str, Any]:
    item = employer.model_dump(mode="json")
    item["pk"] = keys.employer_pk(employer.employer_id)
    item["sk"] = keys.employer_profile_sk()
    return item


def _from_item(item: dict[str, Any]) -> Employer:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return Employer.model_validate(body)


def put(table: Table, employer: Employer) -> Employer:
    table.put_item(Item=_to_item(employer))
    return employer


def get(table: Table, employer_id: str) -> Employer:
    response = table.get_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.employer_profile_sk()}
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("Employer", employer_id)
    return _from_item(item)


def get_or_none(table: Table, employer_id: str) -> Employer | None:
    response = table.get_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.employer_profile_sk()}
    )
    item = response.get("Item")
    return None if item is None else _from_item(item)
