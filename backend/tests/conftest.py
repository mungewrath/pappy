"""Shared pytest fixtures.

`dynamodb_table` starts a moto-mocked DynamoDB, creates the `pappy` table
with the single-table schema, and yields a boto3 `Table` resource — no
Docker, no AWS credentials, no network. `client` wires that table into the
FastAPI app via a dependency override so router tests exercise the exact
same table instance.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table


@pytest.fixture
def dynamodb_table() -> Iterator[Table]:
    with mock_aws():
        # Imported inside the mock context so boto3 resources it creates
        # are bound to moto's fake backend rather than real AWS.
        from pappy.repo.table import create_table_if_not_exists

        table = create_table_if_not_exists()
        yield table


@pytest.fixture
def client(dynamodb_table: Table) -> Iterator[TestClient]:
    from pappy.api.app import app
    from pappy.api.deps import get_table

    app.dependency_overrides[get_table] = lambda: dynamodb_table
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_table, None)
