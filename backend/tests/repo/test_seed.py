import json
from pathlib import Path

from mypy_boto3_dynamodb.service_resource import Table

from pappy.models.ratetable import RateTable
from pappy.repo import rate_table_repo, seed


def test_seeds_all_files_and_is_idempotent(
    dynamodb_table: Table, rates_2026: RateTable, tmp_path: Path
) -> None:
    next_year = rates_2026.model_dump()
    next_year["tax_year"] = 2027
    (tmp_path / "2026.json").write_text(
        json.dumps(rates_2026.model_dump(mode="json")), encoding="utf-8"
    )
    (tmp_path / "2027.json").write_text(json.dumps(next_year), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a rate table", encoding="utf-8")

    seeded, skipped = seed.seed_from_directory(dynamodb_table, tmp_path)
    assert seeded == ["2026 v1", "2027 v1"]
    assert skipped == []
    assert rate_table_repo.get(dynamodb_table, 2026, 1) == rates_2026

    seeded_again, skipped_again = seed.seed_from_directory(dynamodb_table, tmp_path)
    assert seeded_again == []
    assert skipped_again == ["2026 v1", "2027 v1"]
