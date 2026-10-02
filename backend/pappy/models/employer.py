"""Employer entity (design-doc.md §3.1). One per deployment."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel

from pappy.decimals import StrictDecimal
from pappy.models._update import _set_fields
from pappy.models.common import Address
from pappy.money import Money


class EmployerCreate(BaseModel):
    """Fields supplied by the client when onboarding the employer."""

    legal_name: str
    ein: str
    wa_esd_account_number: str | None = None
    ubi: str | None = None
    address: Address
    # The WA UI experience rate is assigned annually by ESD (design-doc.md
    # §3.1); it is profile data rather than rate-table data because it is
    # specific to this employer's account. Until the annual ESD rate notice
    # is entered, accruals compute at zero.
    wa_ui_experience_rate: StrictDecimal | None = None
    # Dependent care FSA settings (§6.3). The annual *statutory* cap lives in
    # the rate table because it is published annually; a plan may elect less,
    # so this is an optional downward override. `include_employer_taxes` is
    # the §6.3 configurability on whether employer-paid FICA counts toward
    # an eligible claim.
    fsa_plan_limit: Money | None = None
    fsa_include_employer_taxes: bool = False


class EmployerUpdate(BaseModel):
    """Partial update — all fields optional, unset fields are left alone."""

    legal_name: str | None = None
    ein: str | None = None
    wa_esd_account_number: str | None = None
    ubi: str | None = None
    address: Address | None = None
    wa_ui_experience_rate: StrictDecimal | None = None
    fsa_plan_limit: Money | None = None
    fsa_include_employer_taxes: bool | None = None


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
    wa_ui_experience_rate: StrictDecimal | None = None
    fsa_plan_limit: Money | None = None
    fsa_include_employer_taxes: bool = False
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
            wa_ui_experience_rate=data.wa_ui_experience_rate,
            fsa_plan_limit=data.fsa_plan_limit,
            fsa_include_employer_taxes=data.fsa_include_employer_taxes,
            created_at=now,
            updated_at=now,
        )

    def apply_update(self, data: EmployerUpdate) -> Employer:
        return self.model_copy(
            update={**_set_fields(data), "updated_at": datetime.now(UTC)}
        )
