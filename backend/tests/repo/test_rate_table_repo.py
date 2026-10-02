import pytest
from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.ratetable import RateTable
from pappy.repo import rate_table_repo
from pappy.repo.exceptions import AlreadyExistsError, NotFoundError


def test_put_if_absent_and_get_round_trip(dynamodb_table: Table, rates_2026: RateTable) -> None:
    rate_table_repo.put_if_absent(dynamodb_table, rates_2026)

    fetched = rate_table_repo.get(dynamodb_table, 2026, rates_2026.version)
    assert fetched == rates_2026


def test_versions_are_immutable_once_written(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    rate_table_repo.put_if_absent(dynamodb_table, rates_2026)
    with pytest.raises(AlreadyExistsError):
        rate_table_repo.put_if_absent(dynamodb_table, rates_2026)


def test_get_missing_raises(dynamodb_table: Table) -> None:
    with pytest.raises(NotFoundError):
        rate_table_repo.get(dynamodb_table, 2026, 1)


def test_latest_for_year_picks_highest_version(
    dynamodb_table: Table, rates_2026: RateTable
) -> None:
    assert rate_table_repo.latest_for_year(dynamodb_table, 2026) is None

    rate_table_repo.put_if_absent(dynamodb_table, rates_2026)
    # Relative to the shipped file, so a future version bump (§5.2) does not
    # collide with the version already seeded here.
    corrected = rates_2026.model_copy(update={"version": rates_2026.version + 1})
    rate_table_repo.put_if_absent(dynamodb_table, corrected)

    latest = rate_table_repo.latest_for_year(dynamodb_table, 2026)
    assert latest is not None
    assert latest.version == rates_2026.version + 1
    # version n is still readable for runs that reference it (§5.2)
    assert rate_table_repo.get(dynamodb_table, 2026, rates_2026.version) == rates_2026


def test_years_are_isolated(dynamodb_table: Table, rates_2026: RateTable) -> None:
    rate_table_repo.put_if_absent(dynamodb_table, rates_2026)
    next_year = rates_2026.model_copy(update={"tax_year": 2027})
    rate_table_repo.put_if_absent(dynamodb_table, next_year)

    latest_2026 = rate_table_repo.latest_for_year(dynamodb_table, 2026)
    latest_2027 = rate_table_repo.latest_for_year(dynamodb_table, 2027)
    assert latest_2026 is not None and latest_2027 is not None
    assert latest_2026.tax_year == 2026
    assert latest_2027.tax_year == 2027
