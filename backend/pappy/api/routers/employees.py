"""Employee CRUD endpoints, nested under an employer."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from mypy_boto3_dynamodb.service_resource import Table

from pappy.api.deps import get_table
from pappy.models.employee import Employee, EmployeeCreate, EmployeeUpdate
from pappy.services import employee_service

router = APIRouter(prefix="/employers/{employer_id}/employees", tags=["employees"])

TableDep = Annotated[Table, Depends(get_table)]


@router.post("", response_model=Employee, status_code=201)
def create_employee(employer_id: str, data: EmployeeCreate, table: TableDep) -> Employee:
    return employee_service.create_employee(table, employer_id, data)


@router.get("", response_model=list[Employee])
def list_employees(employer_id: str, table: TableDep) -> list[Employee]:
    return employee_service.list_employees(table, employer_id)


@router.get("/{employee_id}", response_model=Employee)
def get_employee(employer_id: str, employee_id: str, table: TableDep) -> Employee:
    return employee_service.get_employee(table, employer_id, employee_id)


@router.patch("/{employee_id}", response_model=Employee)
def update_employee(
    employer_id: str, employee_id: str, data: EmployeeUpdate, table: TableDep
) -> Employee:
    return employee_service.update_employee(table, employer_id, employee_id, data)


@router.delete("/{employee_id}", status_code=204)
def delete_employee(employer_id: str, employee_id: str, table: TableDep) -> None:
    employee_service.delete_employee(table, employer_id, employee_id)
