"""Shared value types used across domain models."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class Address(BaseModel):
    line1: str
    line2: str | None = None
    city: str
    state: str
    zip_code: str


class HourCategory(str, Enum):
    """Category of an `HourLine` (design-doc.md §3.1)."""

    REGULAR = "REGULAR"
    OVERTIME = "OVERTIME"
    PTO = "PTO"
    HOLIDAY = "HOLIDAY"
    SICK = "SICK"
    UNPAID = "UNPAID"


class OvertimePolicy(str, Enum):
    """Per-employee overtime policy (design-doc.md §5.1).

    Configurable per employee; default is that overtime applies.
    """

    APPLIES = "APPLIES"
    EXEMPT = "EXEMPT"


class FilingStatus(str, Enum):
    """Federal filing status from W-4 Step 1(c).

    Pub. 15-T publishes exactly three withholding rate schedules; "Single"
    and "Married Filing Separately" share one schedule, so they are one
    value here (2026 Publication 15-T, Percentage Method Tables).
    """

    SINGLE_OR_MFS = "SINGLE_OR_MFS"
    MARRIED_JOINTLY = "MARRIED_JOINTLY"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class PayRunStatus(str, Enum):
    """Pay run lifecycle state (design-doc.md §3.2)."""

    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"
