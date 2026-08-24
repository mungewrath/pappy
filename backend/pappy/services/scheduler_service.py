"""Scheduler business logic — the hands-off weekly loop (design-doc.md §6.6).

EventBridge Scheduler fires the scheduler Lambda once per reminder cadence;
this module does the work:

1. **WEEKLY_PAY** additionally creates the week's `DRAFT` pay runs, seeded
   from each employee's default schedule (§6.1) — the loop from §3.2's
   "DRAFT created" box.
2. Every rule materializes a `ReminderInstance` keyed by due date
   (idempotent: re-delivery of the same event changes nothing).
3. The instance's email goes out through the configured mailer (SES in a
   deployment; the log transport locally), and the instance is marked SENT.

Unacknowledged reminders stay visible via the API and re-nag (§6.6);
acknowledgement is an API concern (`pappy.api.routers.reminders`).
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import TYPE_CHECKING

from pappy import mailer
from pappy.mailer import MailerError
from pappy.models.payrun import PayRun, PayRunCreate
from pappy.models.reminder import ReminderInstance, ReminderRule, ReminderStatus
from pappy.repo import employee_repo, employer_repo, payrun_repo, reminder_repo
from pappy.services import payrun_service

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

logger = logging.getLogger("pappy.scheduler")

_QUARTERLY_DUE = ((1, 15), (4, 15), (6, 15), (9, 15))


def run_rule(
    table: Table,
    rule: ReminderRule,
    *,
    fire_date: date,
    due_date: date | None = None,
    send_email: bool = True,
    create_weekly_drafts: bool = True,
    employer_id: str | None = None,
) -> list[ReminderInstance]:
    """Run one scheduled rule across all employers.

    `fire_date` is when the schedule fired; the occurrence's due date
    defaults to the rule-specific date derived from it. `send_email=False`
    materializes instances only — used by the test endpoint to exercise the
    path without mail. `create_weekly_drafts=False` runs WEEKLY_PAY as a
    pure reminder, skipping §6.1 draft seeding. `employer_id` scopes the
    run to one employer (the API's test endpoint passes the caller's id,
    §7.1); None means every employer in the table.
    """
    resolved_due = due_date if due_date is not None else _due_date_for(rule, fire_date)

    employers = employer_repo.list_all(table)
    if employer_id is not None:
        employers = [e for e in employers if e.employer_id == employer_id]

    created: list[ReminderInstance] = []
    for employer in employers:
        employer_id = employer.employer_id
        if rule == ReminderRule.WEEKLY_PAY and create_weekly_drafts:
            drafts = _create_weekly_drafts(table, employer_id, pay_date=fire_date)
            if drafts:
                logger.info("created %d draft pay run(s) for %s", len(drafts), employer_id)

        instance = reminder_repo.create(
            table, ReminderInstance.new(employer_id, rule, resolved_due)
        )
        if instance is None:
            # Already materialized for this due date. Duplicate delivery is a
            # no-op — unless the stored copy never got emailed (a previous
            # send failed mid-run), in which case re-fire is exactly when it
            # should retry (§6.6: unacknowledged reminders re-nag).
            existing = reminder_repo.get(
                table, employer_id, resolved_due, rule.value
            )
            if send_email and existing.status == ReminderStatus.PENDING:
                try:
                    sent = _send_instance(table, existing)
                    logger.info(
                        "retried send for %s reminder %s@%s",
                        rule.value,
                        employer_id,
                        resolved_due.isoformat(),
                    )
                    created.append(sent)
                except MailerError:
                    logger.exception("resend failed for %s@%s", employer_id, resolved_due)
            continue

        stored = instance
        if send_email:
            stored = _send_instance(table, instance)
            logger.info(
                "sent %s reminder %s@%s (message_id=%r)",
                rule.value,
                employer_id,
                resolved_due.isoformat(),
                stored.ses_message_id,
            )
        created.append(stored)

    return created


def acknowledge(table: Table, employer_id: str, reminder_id: str) -> ReminderInstance:
    """Acknowledge one occurrence (§6.6); see reminder_repo."""
    return reminder_repo.find_and_acknowledge(table, employer_id, reminder_id)


def _send_instance(table: Table, instance: ReminderInstance) -> ReminderInstance:
    """Email one instance and mark it SENT.

    Raises `MailerError` on transport failure; callers decide whether that
    fails the whole invocation (the Lambda should, so EventBridge Scheduler
    retries it) or surface it to the caller (the test endpoint).
    """
    from_address, to_address = mailer.addresses()
    if mailer.mailer_mode() == mailer.MODE_SES and not (from_address and to_address):
        raise MailerError(
            "PAPPY_REMINDER_FROM_EMAIL / PAPPY_REMINDER_TO_EMAIL must be set "
            "when PAPPY_MAILER=ses"
        )
    try:
        message_id = mailer.send(
            mailer.Email(
                to_address=to_address,
                from_address=from_address,
                subject=instance.subject,
                body=instance.body,
            )
        )
    except Exception as exc:
        raise MailerError(f"could not deliver {instance.rule.value} reminder: {exc}") from exc
    return reminder_repo.save(table, instance.mark_sent(message_id=message_id))


def _create_weekly_drafts(table: Table, employer_id: str, *, pay_date: date) -> list[PayRun]:
    """Open this week's draft per employee, Mon–Fri of the pay-date week.

    Skips employees who already have any run at that pay date (manual early
    creation, or a re-fired schedule) so re-delivery cannot double-book the
    week. Terminated employees and hires-in-the-future are skipped too.
    """
    period_start = pay_date - timedelta(days=pay_date.weekday())  # Monday
    period_end = period_start + timedelta(days=4)  # Friday

    existing = {
        run.employee_id
        for run in payrun_repo.list_for_employer(table, employer_id)
        if run.pay_date == pay_date
    }

    drafts = []
    for employee in employee_repo.list_for_employer(table, employer_id):
        if employee.termination_date is not None and employee.termination_date <= period_end:
            continue
        if employee.hire_date > period_end:
            continue
        if employee.employee_id in existing:
            continue
        drafts.append(
            payrun_service.create_draft(
                table,
                employer_id,
                employee.employee_id,
                PayRunCreate(period_start=period_start, period_end=period_end, pay_date=pay_date),
            )
        )
    return drafts


def _due_date_for(rule: ReminderRule, fire_date: date) -> date:
    """The obligation date a firing on `fire_date` points at.

    Schedules fire a few days ahead of their obligation (see
    terraform/modules/scheduling), so this maps fire date -> due date:

    - WEEKLY_PAY: the Friday itself — review happens today.
    - QUARTERLY_TAX: fires the 8th of Jan/Apr/Jun/Sep; due is that quarter's
      estimated-tax date (the 15th).
    - WA_ESD_QUARTERLY: fires the 28th after quarter close; EAMS filing is
      due the last day of the month.
    - W2_EMPLOYEE / IRS_GUIDANCE: mid-January fires; deadline Jan 31.
    - ANNUAL_ROLLOVER: fires Jan 5; verify rates before mid-January.
    - SCHEDULE_H: fires Mar 15; due with Form 1040 on Apr 15.
    """
    match rule:
        case ReminderRule.WEEKLY_PAY:
            return fire_date
        case ReminderRule.QUARTERLY_TAX:
            for month, day in _QUARTERLY_DUE:
                candidate = date(fire_date.year, month, day)
                if candidate >= fire_date:
                    return candidate
            return date(fire_date.year + 1, *_QUARTERLY_DUE[0])
        case ReminderRule.WA_ESD_QUARTERLY:
            if fire_date.month == 12:
                return date(fire_date.year, 12, 31)
            return date(fire_date.year, fire_date.month + 1, 1) - timedelta(days=1)
        case ReminderRule.W2_EMPLOYEE | ReminderRule.IRS_GUIDANCE:
            return date(fire_date.year, 1, 31)
        case ReminderRule.ANNUAL_ROLLOVER:
            return date(fire_date.year, 1, 15)
        case ReminderRule.SCHEDULE_H:
            return date(fire_date.year, 4, 15)
