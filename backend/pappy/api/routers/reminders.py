"""Reminder endpoints (design-doc.md §6.6).

Reminders are materialized by the scheduler Lambda, but the dashboard owns
their lifecycle from there: list what's open, acknowledge it. The
test-send endpoint is the programmatic trigger for firing a rule on demand
— it runs exactly what the scheduled event would run (`scheduler_service.
run_rule`), scoped to the authenticated employer.

`NotFoundError` / `InvalidStateError` / `MailerError` are translated by the
global handlers in `pappy.api.errors`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from pappy.api.deps import EmployerIdDep, get_table
from pappy.mailer import mailer_mode
from pappy.models.reminder import ReminderInstance, ReminderRule
from pappy.repo import reminder_repo
from pappy.services import scheduler_service

router = APIRouter(prefix="/reminders", tags=["reminders"])

TableDep = Annotated[Any, Depends(get_table)]


@router.get("", response_model=list[ReminderInstance])
def list_reminders(
    table: TableDep,
    employer_id: EmployerIdDep,
    open_only: bool = True,
) -> list[ReminderInstance]:
    """Open reminders by default — the unacknowledged set that re-nags
    (§6.6). `?open_only=false` includes acknowledged history."""
    return reminder_repo.list_for_employer(table, employer_id, open_only=open_only)


@router.post("/{reminder_id}/acknowledge", response_model=ReminderInstance)
def acknowledge_reminder(
    reminder_id: str, table: TableDep, employer_id: EmployerIdDep
) -> ReminderInstance:
    """Acknowledge one occurrence; it stops nagging."""
    return scheduler_service.acknowledge(table, employer_id, reminder_id)


class TestSendRequest(BaseModel):
    """Body for firing a rule on demand.

    Mirrors the EventBridge schedule payload plus overrides so one request
    can exercise any cadence at any date without touching AWS: `rule`
    selects the cadence, `fire_date`/`due_date` pin the week or obligation
    date, `create_drafts=false` skips §6.1 draft seeding, and
    `send_email=false` materializes only (useful while SES identities are
    still unverified).
    """

    rule: ReminderRule = ReminderRule.WEEKLY_PAY
    fire_date: date | None = None
    due_date: date | None = None
    create_drafts: bool = True
    send_email: bool = True


class TestSendResponse(BaseModel):
    created: list[ReminderInstance]
    email_transport: str


@router.post("/test-send", response_model=TestSendResponse, status_code=201)
def test_send(
    data: TestSendRequest, table: TableDep, employer_id: EmployerIdDep
) -> TestSendResponse:
    """Fire a reminder rule right now for the caller's employer.

    Same code path as the scheduled Lambda — including idempotency, so
    re-firing the same rule + due date changes nothing.
    """
    fire_date = data.fire_date if data.fire_date is not None else datetime.now(UTC).date()
    created = scheduler_service.run_rule(
        table,
        data.rule,
        fire_date=fire_date,
        due_date=data.due_date,
        send_email=data.send_email,
        create_weekly_drafts=data.create_drafts,
        employer_id=employer_id,
    )
    return TestSendResponse(created=created, email_transport=mailer_mode())
