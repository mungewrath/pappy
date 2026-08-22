"""Employee CRUD + W-4 election business logic."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.employee import Employee, EmployeeCreate, EmployeeUpdate
from pappy.models.w4 import W4Election
from pappy.repo import employee_repo, employer_repo, w4_repo


def create_employee(table: Table, employer_id: str, data: EmployeeCreate) -> Employee:
    # Confirms the employer exists rather than silently orphaning the record.
    employer_repo.get(table, employer_id)
    employee = Employee.new(employer_id=employer_id, employee_id=uuid.uuid4().hex, data=data)
    return employee_repo.put(table, employee)


def get_employee(table: Table, employer_id: str, employee_id: str) -> Employee:
    return employee_repo.get(table, employer_id, employee_id)


def list_employees(table: Table, employer_id: str) -> list[Employee]:
    return employee_repo.list_for_employer(table, employer_id)


def update_employee(
    table: Table, employer_id: str, employee_id: str, data: EmployeeUpdate
) -> Employee:
    existing = employee_repo.get(table, employer_id, employee_id)
    updated = existing.apply_update(data)
    return employee_repo.put(table, updated)


def delete_employee(table: Table, employer_id: str, employee_id: str) -> None:
    employee_repo.get(table, employer_id, employee_id)  # 404s if missing
    employee_repo.delete(table, employer_id, employee_id)


def add_w4_election(
    table: Table, employer_id: str, employee_id: str, election: W4Election
) -> W4Election:
    """Record an effective-dated W-4 election (design-doc.md §5.3).

    Re-submitting an existing effective date replaces that row (a same-day
    correction); a new effective date adds a row without touching history,
    so earlier finalized runs keep resolving to the election that was in
    effect when they were paid.
    """
    employee_repo.get(table, employer_id, employee_id)  # 404s if missing
    return w4_repo.put(table, employer_id, employee_id, election)


def list_w4_elections(table: Table, employer_id: str, employee_id: str) -> list[W4Election]:
    employee_repo.get(table, employer_id, employee_id)  # 404s if missing
    return w4_repo.list_for_employee(table, employer_id, employee_id)
