"""Reminder entities (design-doc.md §3.1, §6.6).

A `ReminderRule` is a class of obligation (weekly pay review, quarterly
estimate, …); a `ReminderInstance` is one materialized occurrence of it,
keyed by due date (§4: SK=`REMINDER#<dueDate>#<ruleId>`, which makes a
re-fired schedule for the same date an idempotent no-op instead of a
duplicate email).

Instances are **acknowledgeable**: an unacknowledged reminder stays visible
on the dashboard and re-nags (§6.6), so a missed quarterly payment doesn't
disappear into an inbox.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from enum import Enum

from pydantic import BaseModel


class ReminderRule(str, Enum):
    """The seven reminder classes from design-doc.md §6.6."""

    WEEKLY_PAY = "WEEKLY_PAY"
    QUARTERLY_TAX = "QUARTERLY_TAX"
    WA_ESD_QUARTERLY = "WA_ESD_QUARTERLY"
    W2_EMPLOYEE = "W2_EMPLOYEE"
    ANNUAL_ROLLOVER = "ANNUAL_ROLLOVER"
    SCHEDULE_H = "SCHEDULE_H"
    IRS_GUIDANCE = "IRS_GUIDANCE"


class ReminderStatus(str, Enum):
    """Lifecycle of one occurrence: created -> emailed -> acknowledged.

    `PENDING` covers instances that exist but whose email hasn't been
    confirmed sent (send failure, or materialized without send — e.g. by the
    test endpoint with `send_email=false`).
    """

    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ReminderInstance(BaseModel):
    """One occurrence of a rule, due on a specific date.

    Key: PK=`EMPLOYER#<id>`, SK=`REMINDER#<dueDate>#<rule>` (design-doc.md §4).
    The key *is* the identity — there is exactly one instance per
    (employer, due date, rule), so re-delivering the same scheduled event is
    idempotent.
    """

    employer_id: str
    rule: ReminderRule
    due_date: date
    status: ReminderStatus = ReminderStatus.PENDING
    subject: str
    body: str
    ses_message_id: str | None = None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None

    @classmethod
    def new(cls, employer_id: str, rule: ReminderRule, due_date: date) -> ReminderInstance:
        """Build an unsent instance, rendering the rule's email content."""
        now = datetime.now(UTC)
        subject, body = render(rule, due_date)
        return cls(
            employer_id=employer_id,
            rule=rule,
            due_date=due_date,
            status=ReminderStatus.PENDING,
            subject=subject,
            body=body,
            created_at=now,
            updated_at=now,
        )

    def mark_sent(self, *, message_id: str | None) -> ReminderInstance:
        now = datetime.now(UTC)
        return self.model_copy(
            update={
                "status": ReminderStatus.SENT,
                "ses_message_id": message_id,
                "sent_at": now,
                "updated_at": now,
            }
        )

    def acknowledge(self) -> ReminderInstance:
        now = datetime.now(UTC)
        return self.model_copy(
            update={"status": ReminderStatus.ACKNOWLEDGED, "acknowledged_at": now, "updated_at": now}
        )


def render(rule: ReminderRule, due_date: date) -> tuple[str, str]:
    """Subject + plain-text body for a rule's occurrence.

    Deliberately informational rather than authoritative (§6.6): the
    IRS-guidance mail links to current publications instead of stating rules.
    """
    due = f" due {due_date.isoformat()}"
    match rule:
        case ReminderRule.WEEKLY_PAY:
            return (
                f"Pappy: payroll review due {due_date.isoformat()}",
                (
                    "This week's pay run draft has been created from the default "
                    "schedule.\n\nOpen Pappy, adjust any exceptions to the week "
                    "(sick day, late night), then confirm to finalize and issue "
                    "the pay stub.\n\n— Pappy"
                ),
            )
        case ReminderRule.QUARTERLY_TAX:
            return (
                f"Pappy: federal estimated tax{due}",
                (
                    "A quarterly Form 1040-ES payment date is approaching.\n\n"
                    "The computed figure arrives once quarterly 1040-ES "
                    "generation ships (design-doc.md §9 phase 6). Withheld FIT "
                    "plus employer Social Security/Medicare accruals are owed "
                    "quarterly — verify amounts against your ledger before "
                    "paying.\n\n— Pappy"
                ),
            )
        case ReminderRule.WA_ESD_QUARTERLY:
            return (
                f"Pappy: WA ESD quarterly report{due}",
                (
                    "The quarter has closed — file the Washington ESD quarterly "
                    "report in EAMS for UI, PFML, and WA Cares.\n\nThe wage "
                    "figures to enter ship with quarterly reporting generation "
                    "(phase 6); meanwhile they are in each finalized run's "
                    "employer accruals.\n\n— Pappy"
                ),
            )
        case ReminderRule.W2_EMPLOYEE:
            return (
                f"Pappy: W-2 delivery deadline{due}",
                (
                    "Provide W-2 Copies B/C/2 to the employee by January 31.\n\n"
                    "Generate the year-end packet from Pappy when it ships "
                    "(phase 6). File Copy A electronically through SSA Business "
                    "Services Online — this app does not print Copy A (§6.5).\n\n"
                    "— Pappy"
                ),
            )
        case ReminderRule.ANNUAL_ROLLOVER:
            return (
                f"Pappy: annual rate rollover checklist{due}",
                (
                    "Verify this year's statutory values against current "
                    "publications before the first pay run of the year:\n\n"
                    "- Social Security wage base and rate\n"
                    "- Medicare rate and additional-Medicare threshold\n"
                    "- Pub. 15-T percentage-method tables (both table sets)\n"
                    "- FUTA rate/wage base and WA credit-reduction status\n"
                    "- WA UI experience rate from the ESD rate notice\n"
                    "- WA PFML and WA Cares rates\n"
                    "- Household-employer coverage thresholds ($2,800 cash-wage "
                    "test for 2025/2026 — confirm)\n\n"
                    "Update rates/<year>.json, then load it into the app.\n\n— Pappy"
                ),
            )
        case ReminderRule.SCHEDULE_H:
            return (
                f"Pappy: Schedule H preparation{due}",
                (
                    "Tax-filing season: generate Schedule H (Form 1040) from "
                    "last year's finalized runs when the generator ships "
                    "(phase 6).\n\n— Pappy"
                ),
            )
        case ReminderRule.IRS_GUIDANCE:
            return (
                f"Pappy: annual IRS guidance check{due}",
                (
                    'Confirm nothing changed for the new year ("confirm nothing '
                    'changed" checklist, §6.6):\n\n'
                    "- Publication 926 (Household Employer's Tax Guide): "
                    "https://www.irs.gov/publications/p926\n"
                    "- Publication 15-T (Federal Income Tax Withholding): "
                    "https://www.irs.gov/publications/p15t\n"
                    "- Schedule H (Form 1040) instructions: "
                    "https://www.irs.gov/instructions/i1040shh\n"
                    "- WA ESD household/domestic employers: "
                    "https://esd.wa.gov/ui-employers/household-employers\n\n"
                    "These links point at authoritative sources; this app is "
                    "never the last word on a statutory question.\n\n— Pappy"
                ),
            )
