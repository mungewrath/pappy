"""Scheduler Lambda entrypoint — invoked by EventBridge Scheduler (§6.6).

Event payloads are the fixed JSON each schedule carries, e.g.:

    {"rule": "WEEKLY_PAY"}

Two manual-trigger paths are supported on purpose:

- An empty event `{}` (or no body) runs `WEEKLY_PAY` for today — so a test
  invocation straight from the Lambda console (`Test` button, default
  event) exercises the whole weekly loop.
- EventBridge Scheduler one-off schedules created in the console can target
  this function with any rule payload to fire it at an arbitrary time.

Anything else unparseable fails loudly: a silently swallowed schedule misfire
is how "the reminder never came" stories start.
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Any

from pappy.models.reminder import ReminderRule
from pappy.repo.table import get_table
from pappy.services import scheduler_service

logger = logging.getLogger("pappy.scheduler")

DEFAULT_RULE = ReminderRule.WEEKLY_PAY


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    rule = _parse_reminder_rule(event)
    fire_date = _parse_fire_date(event)
    logger.info("scheduler fired: rule=%s fire_date=%s", rule.value, fire_date.isoformat())

    created = scheduler_service.run_rule(get_table(), rule, fire_date=fire_date)

    return {
        "rule": rule.value,
        "fire_date": fire_date.isoformat(),
        "reminders_created": len(created),
        "reminders": [
            {
                "employer_id": r.employer_id,
                "due_date": r.due_date.isoformat(),
                "status": r.status.value,
            }
            for r in created
        ],
    }


def _parse_reminder_rule(event: dict[str, Any]) -> ReminderRule:
    raw = event.get("rule")
    if raw is None:
        # Deliberate default: console Test invocations and empty scheduled
        # inputs mean "run the weekly loop now".
        return DEFAULT_RULE
    try:
        return ReminderRule(raw)
    except ValueError as exc:
        raise ValueError(f"Unknown reminder rule in event: {raw!r}") from exc


def _parse_fire_date(event: dict[str, Any]) -> date:
    """`fire_date` override for manual triggers; otherwise today (UTC).

    The weekly cadence fires 06:00 America/Los_Angeles, which is always the
    same UTC-side calendar day, so UTC-today is the correct pay date.
    """
    raw = event.get("fire_date")
    if isinstance(raw, str) and raw:
        return date.fromisoformat(raw)
    return datetime.now(UTC).date()
