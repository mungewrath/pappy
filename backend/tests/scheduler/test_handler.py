"""Scheduler Lambda handler tests — event parsing and dispatch."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import Address
from pappy.models.employer import Employer, EmployerCreate
from pappy.repo import employer_repo
from pappy.scheduler import handler as scheduler_handler


def _employer(table: Table, employer_id: str = "emp-1") -> None:
    employer = Employer.new(
        employer_id,
        EmployerCreate(
            legal_name="Jane Doe",
            ein="12-3456789",
            address=Address(line1="1 Main St", city="Seattle", state="WA", zip_code="98101"),
        ),
    )
    employer_repo.put(table, employer)


def test_empty_event_defaults_to_weekly_pay_today(
    dynamodb_table: Table, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Console `Test` invocations with a default `{}` payload must work."""
    _employer(dynamodb_table)
    monkeypatch.setattr(scheduler_handler, "get_table", lambda: dynamodb_table)

    result = scheduler_handler.handler({}, None)

    assert result["rule"] == "WEEKLY_PAY"
    assert result["reminders_created"] == 1
    assert result["reminders"][0]["status"] == "SENT"


def test_explicit_rule_and_fire_date(dynamodb_table: Table, monkeypatch: pytest.MonkeyPatch) -> None:
    _employer(dynamodb_table)
    monkeypatch.setattr(scheduler_handler, "get_table", lambda: dynamodb_table)

    result = scheduler_handler.handler({"rule": "SCHEDULE_H"}, None)

    assert result["rule"] == "SCHEDULE_H"
    assert result["fire_date"] == datetime.now(UTC).date().isoformat()
    assert len(result["reminders"]) == 1


def test_unknown_rule_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(scheduler_handler, "get_table", lambda: object())
    with pytest.raises(ValueError, match="Unknown reminder rule"):
        scheduler_handler.handler({"rule": "NOT_A_RULE"}, None)
