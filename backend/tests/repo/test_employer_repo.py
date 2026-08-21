import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.common import Address
from pappy.models.employer import Employer, EmployerCreate, EmployerUpdate
from pappy.repo import employer_repo
from pappy.repo.exceptions import NotFoundError


def _address() -> Address:
    return Address(line1="1 Main St", city="Seattle", state="WA", zip_code="98101")


def test_put_and_get_round_trip(dynamodb_table: Table) -> None:
    employer = Employer.new(
        employer_id="emp-1",
        data=EmployerCreate(legal_name="Jane Doe", ein="12-3456789", address=_address()),
    )
    employer_repo.put(dynamodb_table, employer)

    fetched = employer_repo.get(dynamodb_table, "emp-1")
    assert fetched.legal_name == "Jane Doe"
    assert fetched.ein == "12-3456789"
    assert fetched.address.city == "Seattle"


def test_get_missing_raises_not_found(dynamodb_table: Table) -> None:
    with pytest.raises(NotFoundError):
        employer_repo.get(dynamodb_table, "does-not-exist")


def test_get_or_none(dynamodb_table: Table) -> None:
    assert employer_repo.get_or_none(dynamodb_table, "nope") is None


def test_apply_update_only_touches_set_fields(dynamodb_table: Table) -> None:
    employer = Employer.new(
        employer_id="emp-1",
        data=EmployerCreate(legal_name="Jane Doe", ein="12-3456789", address=_address()),
    )
    employer_repo.put(dynamodb_table, employer)

    updated = employer.apply_update(EmployerUpdate(ubi="600123456"))
    employer_repo.put(dynamodb_table, updated)

    fetched = employer_repo.get(dynamodb_table, "emp-1")
    assert fetched.ubi == "600123456"
    assert fetched.legal_name == "Jane Doe"  # untouched
