"""PayRun repo — PK=`EMPLOYER#<id>`, SK=`PAYRUN#<payDate>#<runId>`.

Per design-doc.md §3.2, a DRAFT run is freely editable but a FINALIZED run
is append-only. `put_draft` and `finalize` enforce that with conditional
writes rather than trusting the caller:

- `put_draft` (create or edit) fails if an item exists in a non-DRAFT state.
- `finalize` fails unless the stored item is still DRAFT (a version of the
  "one `TransactWriteItems` with a condition that the run is still DRAFT"
  pattern the design doc calls for — the YTD-accumulator half of that
  transaction is future work, see `PayRun.finalize`'s docstring).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import PayRunStatus
from pappy.models.payrun import PayRun
from pappy.repo import keys
from pappy.repo.exceptions import InvalidStateError, NotFoundError


def _to_item(run: PayRun) -> dict[str, Any]:
    item = run.model_dump(mode="json")
    item["pk"] = keys.employer_pk(run.employer_id)
    item["sk"] = keys.payrun_sk(run.pay_date, run.run_id)
    return item


def _from_item(item: dict[str, Any]) -> PayRun:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return PayRun.model_validate(body)


def create(table: Table, run: PayRun) -> PayRun:
    """Insert a brand-new draft. Fails if a run already exists at this key."""
    try:
        table.put_item(
            Item=_to_item(run),
            ConditionExpression=Attr("pk").not_exists() & Attr("sk").not_exists(),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError(
                f"PayRun already exists: {run.employer_id}/{run.run_id}"
            ) from exc
        raise
    return run


def get(table: Table, employer_id: str, pay_date: date, run_id: str) -> PayRun:
    response = table.get_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.payrun_sk(pay_date, run_id)}
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("PayRun", run_id)
    return _from_item(item)


def find(table: Table, employer_id: str, run_id: str) -> PayRun:
    """Look up a run by ID alone, since the pay date isn't known by callers
    without a prior read. This scans the employer's pay-run partition -- fine
    at the ~52-runs-per-year scale of this app (design-doc.md §2)."""
    response = table.query(
        KeyConditionExpression=Key("pk").eq(keys.employer_pk(employer_id))
        & Key("sk").begins_with(keys.payrun_sk_prefix()),
        FilterExpression=Attr("run_id").eq(run_id),
    )
    items = response.get("Items", [])
    if not items:
        raise NotFoundError("PayRun", run_id)
    return _from_item(items[0])


def list_for_employer(table: Table, employer_id: str, *, year: int | None = None) -> list[PayRun]:
    response = table.query(
        KeyConditionExpression=Key("pk").eq(keys.employer_pk(employer_id))
        & Key("sk").begins_with(keys.payrun_sk_prefix(year))
    )
    runs = [_from_item(item) for item in response.get("Items", [])]
    return sorted(runs, key=lambda r: (r.pay_date, r.run_id))


def save_draft(table: Table, run: PayRun) -> PayRun:
    """Persist edits to a DRAFT run. Fails if the stored run is not DRAFT."""
    if run.status != PayRunStatus.DRAFT:
        raise InvalidStateError(f"Cannot save non-draft PayRun via save_draft: {run.run_id}")
    try:
        table.put_item(
            Item=_to_item(run),
            ConditionExpression=Attr("status").eq(PayRunStatus.DRAFT.value),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError(
                f"PayRun is no longer a draft, cannot edit: {run.run_id}"
            ) from exc
        raise
    return run


def finalize(table: Table, run: PayRun, *, rate_table_version: int) -> PayRun:
    """Transition a DRAFT run to FINALIZED with a conditional write.

    NOTE: design-doc.md §4 specifies this as one `TransactWriteItems` call
    that also advances the YTD accumulator item. That accumulator item isn't
    modeled yet (it belongs with the withholding engine); this function only
    performs the PayRun half, guarded by the same DRAFT-only condition so the
    transactional version can be dropped in later without changing callers.
    """
    finalized = run.finalize(rate_table_version=rate_table_version)
    try:
        table.put_item(
            Item=_to_item(finalized),
            ConditionExpression=Attr("status").eq(PayRunStatus.DRAFT.value),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError(
                f"PayRun is not a draft, cannot finalize: {run.run_id}"
            ) from exc
        raise
    return finalized
