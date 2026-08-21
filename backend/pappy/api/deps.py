"""Shared FastAPI dependencies.

`get_table` is overridden in tests to point at a moto-backed table; in
Lambda/local-uvicorn it resolves against real DynamoDB / DynamoDB Local via
`pappy.repo.table.get_table` (env-var configured, see that module).

Auth is out of scope for this pass (design-doc.md §7.1 covers Cognito/JWT at
the API Gateway layer); `get_employer_id` is a placeholder that will be
replaced by "derive employerId from the token's `sub` claim" once the
authorizer is wired up. For now it accepts an explicit path parameter.
"""

from __future__ import annotations

from functools import lru_cache

from mypy_boto3_dynamodb.service_resource import Table

from pappy.repo.table import get_table as _get_table


@lru_cache(maxsize=1)
def _cached_table() -> Table:
    return _get_table()


def get_table() -> Table:
    return _cached_table()
