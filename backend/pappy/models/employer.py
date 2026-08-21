"""Employer entity (design-doc.md §3.1). One per deployment."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from pappy.models.common import Address


class EmployerCreate(BaseModel):
    """Fields supplied by the client when onboarding the employer."""

    legal_name: str
    ein: str
    wa_esd_account_number: str | None = None
    ubi: str | None = None
    address: Address


class EmployerUpdate(BaseModel):
    """Partial update — all fields optional, unset fields are left alone."""

    legal_name: str | None = None
    ein: str | None = None
    wa_esd_account_number: str | None = None
    ubi: str | None = None
    address: Address | None = None


class Employer(BaseModel):
    """Stored employer profile.

    Key: PK=`EMPLOYER#<id>`, SK=`PROFILE` (design-doc.md §4).
    """

    employer_id: str
    legal_name: str
    ein: str
    wa_esd_account_number: str | None = None
    ubi: str | None = None
    address: Address
    created_at: datetime
    updated_at: datetime

    @classmethod
    def new(cls, employer_id: str, data: EmployerCreate) -> Employer:
        now = datetime.now(UTC)
        return cls(
            employer_id=employer_id,
            legal_name=data.legal_name,
            ein=data.ein,
            wa_esd_account_number=data.wa_esd_account_number,
            ubi=data.ubi,
            address=data.address,
            created_at=now,
            updated_at=now,
        )

    def apply_update(self, data: EmployerUpdate) -> Employer:
        updates = data.model_dump(exclude_unset=True)
        return self.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
