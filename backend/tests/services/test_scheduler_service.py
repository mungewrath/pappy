"""Scheduler service tests — the weekly loop end to end against moto
DynamoDB, with the log mailer (no network)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.mailer import MailerError
from pappy.models.common import Address
from pappy.models.employer import Employer, EmployerCreate
from pappy.models.reminder import ReminderRule, ReminderStatus
from pappy.repo import employer_repo, payrun_repo
from pappy.services import scheduler_service

EMPLOYER_ADDRESS = Address(line1="1 Main St", city="Seattle", state="WA", zip_code="98101")
EMPLOYEE_ADDRESS = Address(line1="2 Elm St", city="Seattle", state="WA", zip_code="98102")


def _employer(table: Table, employer_id: str = "emp-1") -> Employer:
    employer = Employer.new(
        employer_id,
        EmployerCreate(
            legal_name="Jane Doe",
            ein="12-3456789",
            address=EMPLOYER_ADDRESS,
        ),
    )
    return employer_repo.put(table, employer)


def _employee(table: Table, employer_id: str = "emp-1") -> None:
    from pappy.models.employee import DefaultScheduleLine, Employee, EmployeeCreate
    from pappy.repo import employee_repo

    employee = Employee.new(
        employer_id,
        "nanny-1",
        EmployeeCreate(
            full_name="Nanny Smith",
            address=EMPLOYEE_ADDRESS,
            hire_date=date(2026, 1, 1),
            hourly_rate=Decimal("25.00"),
            default_schedule=[
                DefaultScheduleLine(weekday=weekday, hours=Decimal(9))
                for weekday in range(5)
            ],
        ),
    )
    employee_repo.put(table, employee)


FRIDAY = date(2026, 1, 16)  # a Friday


def test_weekly_pay_creates_draft_and_sent_reminder(dynamodb_table: Table) -> None:
    _employer(dynamodb_table)
    _employee(dynamodb_table)

    created = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY
    )

    assert len(created) == 1
    reminder = created[0]
    assert reminder.due_date == FRIDAY
    assert reminder.status == ReminderStatus.SENT
    assert reminder.sent_at is not None

    # §6.1: one draft seeded Mon–Fri from the default schedule.
    runs = payrun_repo.list_for_employer(dynamodb_table, "emp-1")
    assert len(runs) == 1
    run = runs[0]
    assert (run.period_start, run.period_end, run.pay_date) == (
        date(2026, 1, 12),
        date(2026, 1, 16),
        FRIDAY,
    )
    assert len(run.hour_lines) == 5


def test_refiring_same_week_is_a_no_op(dynamodb_table: Table) -> None:
    _employer(dynamodb_table)
    _employee(dynamodb_table)

    first = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY
    )
    again = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY
    )

    assert len(first) == 1 and not again
    assert len(payrun_repo.list_for_employer(dynamodb_table, "emp-1")) == 1


def test_refire_resends_pending_after_failed_send(dynamodb_table: Table) -> None:
    """A send that failed mid-run must retry on the next firing — otherwise
    a stranded PENDING instance is never emailed (§6.6 re-nag)."""
    _employer(dynamodb_table)

    stranded = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY, send_email=False
    )
    assert stranded[0].status == ReminderStatus.PENDING

    retried = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY
    )

    assert len(retried) == 1
    assert retried[0].status == ReminderStatus.SENT

    # A third firing finds it SENT and does nothing.
    assert (
        scheduler_service.run_rule(dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY)
        == []
    )


def test_send_email_false_leaves_pending_and_skips_no_drafts(dynamodb_table: Table) -> None:
    _employer(dynamodb_table)

    created = scheduler_service.run_rule(
        dynamodb_table,
        ReminderRule.WEEKLY_PAY,
        fire_date=FRIDAY,
        send_email=False,
        create_weekly_drafts=False,
    )

    assert created[0].status == ReminderStatus.PENDING
    assert payrun_repo.list_for_employer(dynamodb_table, "emp-1") == []


def test_employer_scoping(dynamodb_table: Table) -> None:
    _employer(dynamodb_table, "emp-2")

    created = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY, employer_id="nobody"
    )

    assert created == []
    assert payrun_repo.list_for_employer(dynamodb_table, "emp-2") == []


def test_nonweekly_rules_materialize_without_drafts(dynamodb_table: Table) -> None:
    _employer(dynamodb_table)
    _employee(dynamodb_table)

    created = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WA_ESD_QUARTERLY, fire_date=date(2026, 4, 28)
    )

    assert len(created) == 1
    # Fires the 28th after quarter close; due is the last day of that month.
    assert created[0].due_date == date(2026, 4, 30)
    assert payrun_repo.list_for_employer(dynamodb_table, "emp-1") == []


@pytest.mark.parametrize(
    ("fire_date", "expected_due"),
    [
        (date(2026, 1, 8), date(2026, 1, 15)),  # quarterly Q4-2025 estimate
        (date(2026, 4, 8), date(2026, 4, 15)),
        (date(2026, 6, 8), date(2026, 6, 15)),
        (date(2026, 9, 8), date(2026, 9, 15)),
        (date(2026, 10, 28), date(2026, 10, 31)),  # WA ESD after Q3 close
        (date(2026, 1, 12), date(2026, 1, 31)),  # W-2 deadline
        (date(2026, 1, 5), date(2026, 1, 15)),  # rate rollover
        (date(2026, 3, 15), date(2026, 4, 15)),  # Schedule H season
    ],
)
def test_due_date_mapping(fire_date: date, expected_due: date) -> None:
    rule = {
        date(2026, 1, 8): ReminderRule.QUARTERLY_TAX,
        date(2026, 4, 8): ReminderRule.QUARTERLY_TAX,
        date(2026, 6, 8): ReminderRule.QUARTERLY_TAX,
        date(2026, 9, 8): ReminderRule.QUARTERLY_TAX,
        date(2026, 10, 28): ReminderRule.WA_ESD_QUARTERLY,
        date(2026, 1, 12): ReminderRule.W2_EMPLOYEE,
        date(2026, 1, 5): ReminderRule.ANNUAL_ROLLOVER,
        date(2026, 3, 15): ReminderRule.SCHEDULE_H,
    }[fire_date]
    assert scheduler_service._due_date_for(rule, fire_date) == expected_due


def test_acknowledge_through_service(dynamodb_table: Table) -> None:
    _employer(dynamodb_table)
    created = scheduler_service.run_rule(
        dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY
    )

    acked = scheduler_service.acknowledge(
        dynamodb_table, "emp-1", f"{FRIDAY.isoformat()}:WEEKLY_PAY"
    )

    assert acked.status == ReminderStatus.ACKNOWLEDGED
    assert created[0].due_date == FRIDAY


def test_ses_mode_requires_addresses(dynamodb_table: Table, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PAPPY_MAILER", "ses")
    monkeypatch.delenv("PAPPY_REMINDER_FROM_EMAIL", raising=False)
    monkeypatch.delenv("PAPPY_REMINDER_TO_EMAIL", raising=False)
    _employer(dynamodb_table)

    with pytest.raises(MailerError):
        scheduler_service.run_rule(
            dynamodb_table, ReminderRule.WEEKLY_PAY, fire_date=FRIDAY
        )
