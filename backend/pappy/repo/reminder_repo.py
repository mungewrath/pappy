"""Reminder repo — PK=`EMPLOYER#<id>`, SK=`REMINDER#<dueDate>#<ruleId>`.

The key *is* the reminder's identity: `create` uses a conditional put so a
schedule firing twice for the same due date (retry, manual re-trigger) is a
no-op rather than a duplicate instance/email (§6.6). Acknowledgement is a
conditional put that fails once the item is already ACKNOWLEDGED.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any

from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.reminder import ReminderInstance, ReminderStatus
from pappy.repo import keys
from pappy.repo.exceptions import InvalidStateError, NotFoundError


def _to_item(reminder: ReminderInstance) -> dict[str, Any]:
    item = reminder.model_dump(mode="json")
    item["pk"] = keys.employer_pk(reminder.employer_id)
    item["sk"] = keys.reminder_sk(reminder.due_date, reminder.rule.value)
    return item


def _from_item(item: dict[str, Any]) -> ReminderInstance:
    body = {k: v for k, v in item.items() if k not in ("pk", "sk")}
    return ReminderInstance.model_validate(body)


def create(table: Table, reminder: ReminderInstance) -> ReminderInstance | None:
    """Insert a new occurrence; return None if one already exists at this key.

    Returning None instead of raising keeps the scheduler's fire path simple:
    "already materialized" is the expected outcome of a duplicate delivery,
    not an error condition.
    """
    try:
        table.put_item(
            Item=_to_item(reminder),
            ConditionExpression=Attr("pk").not_exists() & Attr("sk").not_exists(),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return None
        raise
    return reminder


def get(table: Table, employer_id: str, due_date: date, rule_id: str) -> ReminderInstance:
    response = table.get_item(
        Key={"pk": keys.employer_pk(employer_id), "sk": keys.reminder_sk(due_date, rule_id)}
    )
    item = response.get("Item")
    if item is None:
        raise NotFoundError("Reminder", f"{rule_id}@{due_date.isoformat()}")
    return _from_item(item)


def save(table: Table, reminder: ReminderInstance) -> ReminderInstance:
    """Whole-item write used by mark-sent/acknowledge transitions.

    Conditioned on the stored copy not already being ACKNOWLEDGED, so a
    late-arriving send confirmation can never resurrect an acknowledged
    reminder into the nagging set.
    """
    try:
        table.put_item(
            Item=_to_item(reminder),
            ConditionExpression=Attr("status").ne(ReminderStatus.ACKNOWLEDGED.value),
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise InvalidStateError(
                f"Reminder already acknowledged: {reminder.rule.value}"
                f"@{reminder.due_date.isoformat()}"
            ) from exc
        raise
    return reminder


def acknowledge(table: Table, employer_id: str, due_date: date, rule_id: str) -> ReminderInstance:
    """Mark an open reminder acknowledged (§6.6). Read-modify-write under the
    not-already-acknowledged condition — no UpdateItem permission needed."""
    current = get(table, employer_id, due_date, rule_id)
    if current.status == ReminderStatus.ACKNOWLEDGED:
        raise InvalidStateError(f"Reminder already acknowledged: {rule_id}@{due_date.isoformat()}")
    return save(table, current.acknowledge())


def find_and_acknowledge(
    table: Table, employer_id: str, reminder_id: str
) -> ReminderInstance:
    """`acknowledge` by composite `<dueDate>#<ruleId>` id (see `find`)."""
    found = find(table, employer_id, reminder_id)
    if found.status == ReminderStatus.ACKNOWLEDGED:
        raise InvalidStateError(f"Reminder already acknowledged: {reminder_id}")
    return save(table, found.acknowledge())


def list_for_employer(
    table: Table, employer_id: str, *, open_only: bool = True
) -> list[ReminderInstance]:
    """All reminders for the employer, newest due date first.

    `open_only` selects the unacknowledged set — what stays visible on the
    dashboard and re-nags (§6.6).
    """
    expression = Key("pk").eq(keys.employer_pk(employer_id)) & Key("sk").begins_with(
        keys.reminder_sk_prefix()
    )
    kwargs: dict[str, Any] = {}
    if open_only:
        kwargs["FilterExpression"] = Attr("status").ne(ReminderStatus.ACKNOWLEDGED.value)
    response = table.query(KeyConditionExpression=expression, **kwargs)
    reminders = [_from_item(item) for item in response.get("Items", [])]
    return sorted(reminders, key=lambda r: r.due_date, reverse=True)


def find(table: Table, employer_id: str, reminder_id: str) -> ReminderInstance:
    """Look up by composite id `<dueDate>:<ruleId>` — the API surfaces the
    reminder this way because the client never needs to know the partition
    layout. `:` keeps the id URL-path-safe; `#` is reserved for the SK."""
    due_part, _, rule_part = reminder_id.partition(":")
    try:
        due_date = date.fromisoformat(due_part)
    except ValueError as exc:
        raise NotFoundError("Reminder", reminder_id) from exc
    return get(table, employer_id, due_date, rule_part)
