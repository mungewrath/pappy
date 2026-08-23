from datetime import date
from decimal import Decimal

import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import Address
from pappy.models.employee import Employee, EmployeeCreate
from pappy.models.employer import Employer, EmployerCreate
from pappy.models.w4 import W4Election
from pappy.repo import employee_repo, employer_repo, w4_repo
from pappy.repo.exceptions import NotFoundError


def _seed(table: Table) -> tuple[str, str]:
    employer = Employer.new(
        employer_id="emp-1",
        data=EmployerCreate(
            legal_name="Jane Doe",
            ein="12-3456789",
            address=Address(line1="1 Main St", city="Seattle", state="WA", zip_code="98101"),
        ),
    )
    employer_repo.put(table, employer)
    employee = Employee.new(
        employer_id="emp-1",
        employee_id="nanny-1",
        data=EmployeeCreate(
            full_name="Nanny Smith",
            address=Address(line1="2 Elm St", city="Seattle", state="WA", zip_code="98102"),
            hire_date=date(2026, 1, 1),
            hourly_rate=Decimal("25.00"),
        ),
    )
    employee_repo.put(table, employee)
    return "emp-1", "nanny-1"


def test_put_and_get_round_trips(dynamodb_table: Table) -> None:
    employer_id, employee_id = _seed(dynamodb_table)

    election = W4Election(effective_date=date(2026, 3, 1), extra_withholding=Decimal("25.00"))
    w4_repo.put(dynamodb_table, employer_id, employee_id, election)

    fetched = w4_repo.get(dynamodb_table, employer_id, employee_id, "2026-03-01")
    assert fetched == election


def test_get_missing_raises(dynamodb_table: Table) -> None:
    with pytest.raises(NotFoundError):
        w4_repo.get(dynamodb_table, "emp-1", "nanny-1", "2026-03-01")


def test_list_sorted_by_effective_date(dynamodb_table: Table) -> None:
    employer_id, employee_id = _seed(dynamodb_table)

    later = W4Election(effective_date=date(2026, 7, 1), extra_withholding=Decimal("50.00"))
    earlier = W4Election(effective_date=date(2026, 1, 1))
    for election in (later, earlier):
        w4_repo.put(dynamodb_table, employer_id, employee_id, election)

    listed = w4_repo.list_for_employee(dynamodb_table, employer_id, employee_id)
    assert [e.effective_date for e in listed] == [date(2026, 1, 1), date(2026, 7, 1)]


def test_same_date_resubmission_replaces_row(dynamodb_table: Table) -> None:
    employer_id, employee_id = _seed(dynamodb_table)

    w4_repo.put(dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1)))
    corrected = W4Election(effective_date=date(2026, 1, 1), extra_withholding=Decimal("10.00"))
    w4_repo.put(dynamodb_table, employer_id, employee_id, corrected)

    listed = w4_repo.list_for_employee(dynamodb_table, employer_id, employee_id)
    assert listed == [corrected]


def test_employee_listing_excludes_w4_items(dynamodb_table: Table) -> None:
    employer_id, employee_id = _seed(dynamodb_table)
    w4_repo.put(dynamodb_table, employer_id, employee_id, W4Election(effective_date=date(2026, 1, 1)))

    employees = employee_repo.list_for_employer(dynamodb_table, employer_id)
    assert [e.employee_id for e in employees] == ["nanny-1"]
