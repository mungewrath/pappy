from datetime import date
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import Address, OvertimePolicy
from pappy.models.employee import Employee, EmployeeCreate
from pappy.repo import employee_repo
from pappy.repo.exceptions import NotFoundError


def _address() -> Address:
    return Address(line1="1 Main St", city="Seattle", state="WA", zip_code="98101")


def _make(employer_id: str, employee_id: str, name: str = "Nanny Smith") -> Employee:
    return Employee.new(
        employer_id=employer_id,
        employee_id=employee_id,
        data=EmployeeCreate(
            full_name=name,
            address=_address(),
            hire_date=date(2026, 1, 1),
            hourly_rate=Decimal("25.00"),
            overtime_policy=OvertimePolicy.APPLIES,
        ),
    )


def test_put_and_get_round_trip(dynamodb_table: Table) -> None:
    employee = _make("emp-1", "nanny-1")
    employee_repo.put(dynamodb_table, employee)

    fetched = employee_repo.get(dynamodb_table, "emp-1", "nanny-1")
    assert fetched.full_name == "Nanny Smith"
    assert fetched.hourly_rate == Decimal("25.00")


def test_get_missing_raises_not_found(dynamodb_table: Table) -> None:
    with pytest.raises(NotFoundError):
        employee_repo.get(dynamodb_table, "emp-1", "does-not-exist")


def test_list_for_employer_only_returns_that_employers_employees(
    dynamodb_table: Table,
) -> None:
    employee_repo.put(dynamodb_table, _make("emp-1", "nanny-1", "A"))
    employee_repo.put(dynamodb_table, _make("emp-1", "nanny-2", "B"))
    employee_repo.put(dynamodb_table, _make("emp-2", "nanny-3", "C"))

    results = employee_repo.list_for_employer(dynamodb_table, "emp-1")
    names = sorted(e.full_name for e in results)
    assert names == ["A", "B"]


def test_delete(dynamodb_table: Table) -> None:
    employee_repo.put(dynamodb_table, _make("emp-1", "nanny-1"))
    employee_repo.delete(dynamodb_table, "emp-1", "nanny-1")
    assert employee_repo.get_or_none(dynamodb_table, "emp-1", "nanny-1") is None
