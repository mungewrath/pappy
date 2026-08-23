"""Employer CRUD business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.employer import Employer, EmployerCreate, EmployerUpdate
from pappy.repo import employer_repo


def create_employer(
    table: Table, employer_id: str, data: EmployerCreate
) -> tuple[Employer, bool]:
    """Get-or-create the profile keyed by the caller's JWT `sub` (§7.1).

    Idempotent by design: onboarding can be re-run from any browser/device
    without duplicating or clobbering the existing profile. The second element
    of the return value is True only when a new row was created.
    """
    existing = employer_repo.get_or_none(table, employer_id)
    if existing is not None:
        return existing, False
    employer = Employer.new(employer_id=employer_id, data=data)
    return employer_repo.put(table, employer), True


def get_employer(table: Table, employer_id: str) -> Employer:
    return employer_repo.get(table, employer_id)


def update_employer(table: Table, employer_id: str, data: EmployerUpdate) -> Employer:
    existing = employer_repo.get(table, employer_id)
    updated = existing.apply_update(data)
    return employer_repo.put(table, updated)
