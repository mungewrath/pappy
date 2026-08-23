"""Single-table DynamoDB access (design-doc.md §2.4, §4).

`get_table()` returns a boto3 DynamoDB `Table` resource, configurable via
environment variables so the same code path works against real AWS, a local
DynamoDB Local endpoint, or (in tests) `moto`'s in-memory fake:

- `PAPPY_TABLE_NAME` (default `pappy`)
- `PAPPY_DYNAMODB_ENDPOINT_URL` — set for DynamoDB Local; unset for AWS/moto
- `AWS_REGION` / `AWS_DEFAULT_REGION` — standard boto3 region resolution

`create_table_if_not_exists()` is a local-dev/test convenience only; in
deployed environments the table is created by Terraform
(`terraform/modules/data`), not by application code.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import boto3
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient
    from mypy_boto3_dynamodb.service_resource import DynamoDBServiceResource, Table

DEFAULT_TABLE_NAME = "pappy"


def _config() -> dict[str, str | None]:
    endpoint_url = os.environ.get("PAPPY_DYNAMODB_ENDPOINT_URL")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
    return {"region_name": region, "endpoint_url": endpoint_url}


def _resource() -> DynamoDBServiceResource:
    config = _config()
    return boto3.resource(
        "dynamodb",
        region_name=config["region_name"],
        endpoint_url=config["endpoint_url"],
    )


def get_client() -> DynamoDBClient:
    """A low-level DynamoDB client sharing the resource's configuration.

    Transactions go through this client rather than `table.meta.client`:
    identical wire behavior against real DynamoDB and DynamoDB Local, and it
    sidesteps a moto quirk with resource-bound clients (see repo/payrun_repo).
    """
    config = _config()
    return boto3.client(
        "dynamodb",
        region_name=config["region_name"],
        endpoint_url=config["endpoint_url"],
    )


def table_name() -> str:
    return os.environ.get("PAPPY_TABLE_NAME", DEFAULT_TABLE_NAME)


def get_table() -> Table:
    return _resource().Table(table_name())


def create_table_if_not_exists() -> Table:
    """Create the `pappy` table with the single-table PK/SK schema.

    Local dev / test convenience only — see module docstring.
    """
    resource = _resource()
    name = table_name()
    try:
        table = resource.Table(name)
        table.load()
        return table
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "ResourceNotFoundException":
            raise

    table = resource.create_table(
        TableName=name,
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    table.wait_until_exists()
    return table
