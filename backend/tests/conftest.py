"""Shared pytest fixtures.

`dynamodb_table` starts a moto-mocked DynamoDB, creates the `pappy` table
with the single-table schema, and yields a boto3 `Table` resource — no
Docker, no AWS credentials, no network. `client` wires that table into the
FastAPI app via a dependency override so router tests exercise the exact
same table instance.

The app derives `employerId` from the JWT `sub` claim (design-doc.md §7.1),
so `client` carries a default `Authorization: Bearer …` header for
`DEFAULT_SUB`; requests can override it per-call to simulate other users.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.ratetable import RateTable

REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_SUB = "test-user-sub"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def bearer(sub: str) -> dict[str, str]:
    """Minimal unsigned JWT carrying `sub`.

    Good enough for tests because local/TestClient traffic reaches
    `get_employer_id` through its unverified-header fallback — production
    tokens are verified by API Gateway before the Lambda runs.
    """
    header = _b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": sub}).encode())
    return {"Authorization": f"Bearer {header}.{payload}.signature"}


@pytest.fixture(scope="session")
def rates_2026() -> RateTable:
    from pappy.models.ratetable import load_rate_table

    return load_rate_table(REPO_ROOT / "rates" / "2026.json")


@pytest.fixture
def dynamodb_table() -> Iterator[Table]:
    with mock_aws():
        # Imported inside the mock context so boto3 resources it creates
        # are bound to moto's fake backend rather than real AWS.
        from pappy.repo.table import create_table_if_not_exists

        table = create_table_if_not_exists()
        yield table


@pytest.fixture
def seeded_rates(dynamodb_table: Table, rates_2026: RateTable) -> RateTable:
    """The 2026 rate table stored in the (moto) table under `RATES#2026`."""
    from pappy.repo import rate_table_repo

    rate_table_repo.put_if_absent(dynamodb_table, rates_2026)
    return rates_2026


@pytest.fixture
def client(dynamodb_table: Table) -> Iterator[TestClient]:
    from pappy.api.app import app
    from pappy.api.deps import get_table

    app.dependency_overrides[get_table] = lambda: dynamodb_table
    try:
        with TestClient(app, headers=bearer(DEFAULT_SUB)) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_table, None)


@pytest.fixture
def auth_headers() -> Callable[[str], dict[str, str]]:
    """Builds Authorization headers for an arbitrary `sub` — for tests that
    exercise identity scoping across users."""
    return bearer
