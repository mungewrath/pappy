"""Reminder repo tests — idempotent materialization + acknowledgement
transitions (design-doc.md §6.6)."""

from __future__ import annotations

from datetime import date

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.reminder import ReminderInstance, ReminderRule, ReminderStatus
from pappy.repo import reminder_repo
from pappy.repo.exceptions import InvalidStateError, NotFoundError


def _new(due: date = date(2026, 1, 16), rule: ReminderRule = ReminderRule.WEEKLY_PAY) -> ReminderInstance:
    return ReminderInstance.new("emp-1", rule, due)


def test_create_is_idempotent_per_due_date_and_rule(dynamodb_table: Table) -> None:
    first = reminder_repo.create(dynamodb_table, _new())
    assert first is not None and first.status == ReminderStatus.PENDING

    # Same (due date, rule) again — a re-fired schedule — changes nothing.
    assert reminder_repo.create(dynamodb_table, _new()) is None

    # A different rule on the same day is still its own instance.
    other = reminder_repo.create(
        dynamodb_table, _new(rule=ReminderRule.ANNUAL_ROLLOVER)
    )
    assert other is not None


def test_get_and_find_by_composite_id(dynamodb_table: Table) -> None:
    created = reminder_repo.create(dynamodb_table, _new())
    assert created is not None

    fetched = reminder_repo.get(
        dynamodb_table, "emp-1", date(2026, 1, 16), ReminderRule.WEEKLY_PAY.value
    )
    assert fetched == created

    by_id = reminder_repo.find(dynamodb_table, "emp-1", "2026-01-16:WEEKLY_PAY")
    assert by_id == created


def test_find_rejects_malformed_id(dynamodb_table: Table) -> None:
    with pytest.raises(NotFoundError):
        reminder_repo.find(dynamodb_table, "emp-1", "not-a-date:WEEKLY_PAY")


def test_mark_sent_via_save(dynamodb_table: Table) -> None:
    created = reminder_repo.create(dynamodb_table, _new())
    assert created is not None

    saved = reminder_repo.save(dynamodb_table, created.mark_sent(message_id="ses-123"))

    fetched = reminder_repo.get(
        dynamodb_table, "emp-1", date(2026, 1, 16), ReminderRule.WEEKLY_PAY.value
    )
    assert fetched.status == ReminderStatus.SENT
    assert fetched.ses_message_id == "ses-123"
    assert fetched.sent_at is not None
    assert saved == fetched


def test_acknowledge_transitions_once_only(dynamodb_table: Table) -> None:
    created = reminder_repo.create(dynamodb_table, _new())
    assert created is not None

    acked = reminder_repo.find_and_acknowledge(
        dynamodb_table, "emp-1", "2026-01-16:WEEKLY_PAY"
    )
    assert acked.status == ReminderStatus.ACKNOWLEDGED
    assert acked.acknowledged_at is not None

    with pytest.raises(InvalidStateError):
        reminder_repo.acknowledge(
            dynamodb_table, "emp-1", date(2026, 1, 16), ReminderRule.WEEKLY_PAY.value
        )
    with pytest.raises(InvalidStateError):
        reminder_repo.find_and_acknowledge(
            dynamodb_table, "emp-1", "2026-01-16:WEEKLY_PAY"
        )


def test_save_cannot_resurrect_acknowledged(dynamodb_table: Table) -> None:
    created = reminder_repo.create(dynamodb_table, _new())
    assert created is not None
    acked = reminder_repo.save(dynamodb_table, created.acknowledge())

    with pytest.raises(InvalidStateError):
        reminder_repo.save(dynamodb_table, acked.mark_sent(message_id="late"))


def test_list_open_excludes_acknowledged_newest_first(dynamodb_table: Table) -> None:
    for due in (date(2026, 1, 9), date(2026, 1, 16)):
        created = reminder_repo.create(dynamodb_table, _new(due=due))
        assert created is not None

    older = reminder_repo.get(
        dynamodb_table, "emp-1", date(2026, 1, 9), ReminderRule.WEEKLY_PAY.value
    )
    reminder_repo.save(dynamodb_table, older.acknowledge())

    open_items = reminder_repo.list_for_employer(dynamodb_table, "emp-1", open_only=True)
    assert [r.due_date for r in open_items] == [date(2026, 1, 16)]

    everything = reminder_repo.list_for_employer(dynamodb_table, "emp-1", open_only=False)
    assert len(everything) == 2


def test_scoping_by_employer(dynamodb_table: Table) -> None:
    mine = reminder_repo.create(dynamodb_table, _new())
    theirs = reminder_repo.create(dynamodb_table, ReminderInstance.new("emp-2", ReminderRule.WEEKLY_PAY, date(2026, 1, 16)))
    assert mine is not None and theirs is not None

    assert len(reminder_repo.list_for_employer(dynamodb_table, "emp-1")) == 1
    with pytest.raises(NotFoundError):
        reminder_repo.get(dynamodb_table, "emp-2", date(2026, 1, 9), ReminderRule.WEEKLY_PAY.value)
