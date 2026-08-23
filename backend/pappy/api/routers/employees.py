"""Employee CRUD + W-4 election endpoints, scoped to the authenticated
caller's employer (§7.1)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.employee import Employee, EmployeeCreate, EmployeeUpdate
from pappy.models.w4 import W4Election
from pappy.services import employee_service

router = APIRouter(prefix="/employees", tags=["employees"])

TableDep = Annotated[Any, Depends(get_table)]


@router.post("", response_model=Employee, status_code=201)
def create_employee(data: EmployeeCreate, table: TableDep, employer_id: EmployerIdDep) -> Employee:
    return employee_service.create_employee(table, employer_id, data)


@router.get("", response_model=list[Employee])
def list_employees(table: TableDep, employer_id: EmployerIdDep) -> list[Employee]:
    return employee_service.list_employees(table, employer_id)


@router.get("/{employee_id}", response_model=Employee)
def get_employee(employee_id: str, table: TableDep, employer_id: EmployerIdDep) -> Employee:
    return employee_service.get_employee(table, employer_id, employee_id)


@router.patch("/{employee_id}", response_model=Employee)
def update_employee(
    employee_id: str, data: EmployeeUpdate, table: TableDep, employer_id: EmployerIdDep
) -> Employee:
    return employee_service.update_employee(table, employer_id, employee_id, data)


@router.delete("/{employee_id}", status_code=204)
def delete_employee(employee_id: str, table: TableDep, employer_id: EmployerIdDep) -> None:
    employee_service.delete_employee(table, employer_id, employee_id)


@router.post("/{employee_id}/w4", response_model=W4Election, status_code=201)
def add_w4_election(
    employee_id: str, data: W4Election, table: TableDep, employer_id: EmployerIdDep
) -> W4Election:
    """Record an effective-dated W-4 election (design-doc.md §5.3). A pay run
    resolves the election in effect on its pay date, so a mid-year re-election
    never rewrites earlier finalized runs."""
    return employee_service.add_w4_election(table, employer_id, employee_id, data)


@router.get("/{employee_id}/w4", response_model=list[W4Election])
def list_w4_elections(
    employee_id: str, table: TableDep, employer_id: EmployerIdDep
) -> list[W4Election]:
    return employee_service.list_w4_elections(table, employer_id, employee_id)
