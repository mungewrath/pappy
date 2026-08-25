"""Outbound reminder email.

Two transports, selected by `PAPPY_MAILER`:

- `ses` (deployed): Amazon SES `SendEmail`. Sandbox mode is sufficient by
  design (§2.2) — recipients are fixed and few, and both sender and
  recipient are verified identities owned by the same account. The IAM
  policy grants `ses:SendEmail` on exactly those identity ARNs (§7.4).
- `log` (default; local dev / tests): the rendered email is written to the
  log instead of being sent. `docker compose up` therefore exercises the
  whole reminder path with no AWS credentials and nothing leaves the box.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import boto3

logger = logging.getLogger("pappy.mailer")

# Under plain uvicorn / `docker compose logs`, nothing configures the root
# logger, so INFO would vanish — configure it here if nobody else did.
# In Lambda the runtime installs its own root handler, so this is skipped
# there (no double logging).
if not logging.getLogger().handlers:
    logging.basicConfig(level=logging.INFO)

MODE_SES = "ses"
MODE_LOG = "log"


class MailerError(Exception):
    """Raised when an email could not be delivered or the transport is
    misconfigured — mapped to a 502 at the API boundary."""


@dataclass(frozen=True)
class Email:
    to_address: str
    from_address: str
    subject: str
    body: str


def mailer_mode() -> str:
    mode = os.environ.get("PAPPY_MAILER", MODE_LOG)
    return mode if mode in (MODE_SES, MODE_LOG) else MODE_LOG


def send(email: Email) -> str | None:
    """Deliver one email; returns the SES message id when actually sent,
    None under the log transport."""
    mode = mailer_mode()
    if mode == MODE_LOG:
        logger.info(
            "EMAIL (log transport; not sent)\n%s",
            json.dumps(
                {
                    "to": email.to_address,
                    "from": email.from_address,
                    "subject": email.subject,
                    "body": email.body,
                },
                indent=2,
            ),
        )
        return None
    client = boto3.client("ses")
    response = client.send_email(
        Source=email.from_address,
        Destination={"ToAddresses": [email.to_address]},
        Message={
            "Subject": {"Data": email.subject, "Charset": "UTF-8"},
            "Body": {"Text": {"Data": email.body, "Charset": "UTF-8"}},
        },
    )
    return str(response["MessageId"])


def addresses() -> tuple[str, str]:
    """(from, to) pair from configuration."""
    from_address = os.environ.get("PAPPY_REMINDER_FROM_EMAIL", "")
    to_address = os.environ.get("PAPPY_REMINDER_TO_EMAIL", "")
    return from_address, to_address
