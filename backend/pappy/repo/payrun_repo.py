"""PayRun repo — PK=`EMPLOYER#<id>`, SK=`PAYRUN#<payDate>#<runId>`.

Per design-doc.md §3.2, a DRAFT run is freely editable but a FINALIZED run
is append-only. `put_draft` and `finalize` enforce that with conditional
writes rather than trusting the caller:

- `put_draft` (create or edit) fails if an item exists in a non-DRAFT state.
- `finalize` is one `TransactWriteItems` (§4) that writes the finalized run
  *and* advances the YTD accumulator atomically, conditioned on the run
  still being DRAFT — so a run can never be finalized twice, and wage-base
  accumulators can never be double-counted.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Attr, Key
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table
    from mypy_boto3_dynamodb.type_defs import TransactWriteItemTypeDef

from pappy.calc.payroll import PayrollResult
from pappy.models.common import PayRunStatus
from pappy.models.payrun import PayRun
from pappy.models.ytd import YtdAccumulator
from pappy.repo import keys, ytd_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError
from pappy.repo.table import get_client

_SERIALIZER = TypeSerializer()


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


def finalize(
    table: Table,
    run: PayRun,
    *,
    rate_table_version: int,
    payroll: PayrollResult,
    tax_year: int,
    prior_ytd: YtdAccumulator | None,
) -> tuple[PayRun, YtdAccumulator]:
    """Transition a DRAFT run to FINALIZED in one transaction (design-doc.md §4).

    Writes two items atomically:

    1. the finalized `PAYRUN` item — `Put`, conditioned on the stored run
       still being DRAFT;
    2. the `YTD` accumulator update — the run's capped wage slices ADDed to
       the year's totals.

    If any part fails (in particular, a concurrent finalization won the
    DRAFT condition), the whole transaction rolls back and neither the run
    nor the accumulator moves — the double-count is structurally impossible,
    not merely discouraged.

    Returns the finalized run and the post-write accumulator value (computed
    from `prior_ytd`, mirroring exactly what the transaction's ADD clauses
    applied).
    """
    finalized = run.finalize(rate_table_version=rate_table_version, payroll=payroll)
    base = prior_ytd if prior_ytd is not None else _empty_ytd(run, tax_year)
    new_ytd = base.apply_taxable(payroll.taxable)
    # The transaction ADDs only this run's capped slices — never the merged
    # totals, which would double-count everything already accumulated.
    delta = _empty_ytd(run, tax_year).apply_taxable(payroll.taxable)

    put_op: TransactWriteItemTypeDef = {
        "Put": {
            "TableName": table.name,
            "Item": _SERIALIZER.serialize(_to_item(finalized))["M"],
            "ConditionExpression": "#status = :draft",
            "ExpressionAttributeNames": {"#status": "status"},
            "ExpressionAttributeValues": {":draft": {"S": PayRunStatus.DRAFT.value}},
        }
    }
    update_op: TransactWriteItemTypeDef = ytd_repo.transact_update_item(
        table, run.employer_id, run.employee_id, tax_year, delta=delta
    )
    try:
        # A directly-built low-level client rather than `table.meta.client` —
        # identical wire format against real DynamoDB/DynamoDB Local, and it
        # avoids a moto quirk with resource-bound clients in tests.
        client = get_client()
        client.transact_write_items(TransactItems=[put_op, update_op])
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            raise InvalidStateError(
                f"PayRun is not a draft, cannot finalize: {run.run_id}"
            ) from exc
        raise
    return finalized, new_ytd


def _empty_ytd(run: PayRun, tax_year: int) -> YtdAccumulator:
    return YtdAccumulator(
        employer_id=run.employer_id,
        employee_id=run.employee_id,
        tax_year=tax_year,
    )
