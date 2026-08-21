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


class PayRunStatus(str, Enum):
    """Pay run lifecycle state (design-doc.md §3.2)."""

    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"
