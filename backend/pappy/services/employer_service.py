"""Employer CRUD business logic."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.employer import Employer, EmployerCreate, EmployerUpdate
from pappy.repo import employer_repo


def create_employer(table: Table, data: EmployerCreate) -> Employer:
    employer = Employer.new(employer_id=uuid.uuid4().hex, data=data)
    return employer_repo.put(table, employer)


def get_employer(table: Table, employer_id: str) -> Employer:
    return employer_repo.get(table, employer_id)


def update_employer(table: Table, employer_id: str, data: EmployerUpdate) -> Employer:
    existing = employer_repo.get(table, employer_id)
    updated = existing.apply_update(data)
    return employer_repo.put(table, updated)
