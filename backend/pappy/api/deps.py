"""Shared FastAPI dependencies.

`get_table` is overridden in tests to point at a moto-backed table; in
Lambda/local-uvicorn it resolves against real DynamoDB / DynamoDB Local via
`pappy.repo.table.get_table` (env-var configured, see that module).

`get_employer_id` scopes every request to the caller (design-doc.md §7.1):
it derives `employerId` from the JWT access token's `sub` claim, so the
client never supplies an employer ID and every DynamoDB key is partitioned
by the authenticated principal.
"""

from __future__ import annotations

import base64
import binascii
import json
import os
from functools import lru_cache
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, HTTPException, Request, status

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.repo.table import get_table as _get_table


@lru_cache(maxsize=1)
def _cached_table() -> Table:
    return _get_table()


def get_table() -> Table:
    return _cached_table()


def _claims_from_api_gateway_event(request: Request) -> dict[str, Any] | None:
    """Claims injected by API Gateway's JWT authorizer, via Mangum.

    Mangum stores the original Lambda event on the ASGI scope (`aws.event`);
    for HTTP APIs with a JWT authorizer the validated claims live at
    `requestContext.authorizer.jwt.claims`. Signature/issuer/audience have
    already been verified by API Gateway before the Lambda was invoked.
    """
    event = request.scope.get("aws.event")
    if not isinstance(event, dict):
        return None
    request_context = event.get("requestContext")
    authorizer = (
        request_context.get("authorizer", {}) if isinstance(request_context, dict) else {}
    )
    jwt = authorizer.get("jwt", {}) if isinstance(authorizer, dict) else {}
    claims = jwt.get("claims") if isinstance(jwt, dict) else None
    return claims if isinstance(claims, dict) else None


def _claims_from_authorization_header(request: Request) -> dict[str, Any] | None:
    """Claims decoded straight from the Authorization header.

    Fallback for paths with no API Gateway in front — direct `uvicorn` local
    development and the TestClient suite. The payload is decoded without
    signature verification: acceptable only because production traffic always
    arrives via the authorizer above (§7.1), which rejects anything unsigned,
    expired, or mis-scoped before the app runs.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (IndexError, ValueError, binascii.Error):
        return None
    return claims if isinstance(claims, dict) else None


def get_employer_id(request: Request) -> str:
    """The authenticated caller's employer id — the token's `sub` claim."""
    for source in (_claims_from_api_gateway_event, _claims_from_authorization_header):
        claims = source(request)
        sub = claims.get("sub") if claims else None
        if isinstance(sub, str) and sub:
            return sub

    # Local-development escape hatch (docker compose / bare uvicorn with no
    # Cognito configured): pin all requests to a fixed principal. Never set
    # this in a deployed environment — Terraform doesn't, and it must stay
    # that way (§7.1).
    dev_fallback = os.environ.get("PAPPY_DEV_FALLBACK_SUB")
    if dev_fallback:
        return dev_fallback

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid authentication token.",
    )


EmployerIdDep = Annotated[str, Depends(get_employer_id)]
