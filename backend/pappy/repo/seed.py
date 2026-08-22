"""Rate-table seeder (design-doc.md §5.2).

Loads every `*.json` under a rates directory into the `RATES#<taxYear>`
partition of the single table. Idempotent: existing versions are skipped
(`rate_table_repo.put_if_absent`), so it is safe to run on every deploy and
every `docker compose up`.

Usage:

    uv run python -m pappy.repo.seed            # reads $PAPPY_RATES_DIR
    PAPPY_RATES_DIR=/path/to/rates uv run python -m pappy.repo.seed

In deployed environments this runs as a CI/deploy step; locally, the compose
`db-init` service runs it after table creation. A malformed rate file fails
loudly here — at load, never at payroll time.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from pappy.models.ratetable import RateTable, parse_rate_table
from pappy.repo import rate_table_repo
from pappy.repo.exceptions import AlreadyExistsError

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

DEFAULT_RATES_DIR = "rates"


def seed_from_directory(table: Table, directory: Path) -> tuple[list[str], list[str]]:
    """Seed every JSON file in `directory`. Returns (seeded, skipped) labels."""
    seeded: list[str] = []
    skipped: list[str] = []
    for path in sorted(directory.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            rate_table = parse_rate_table(json.load(f))
        try:
            rate_table_repo.put_if_absent(table, rate_table)
            seeded.append(_label(rate_table))
        except AlreadyExistsError:
            skipped.append(_label(rate_table))
    return seeded, skipped


def _label(rate_table: RateTable) -> str:
    return f"{rate_table.tax_year} v{rate_table.version}"


def main() -> None:
    from pappy.repo.table import get_table

    directory = Path(os.environ.get("PAPPY_RATES_DIR", DEFAULT_RATES_DIR))
    if not directory.is_dir():
        print(f"seed: rates directory not found: {directory}", file=sys.stderr)
        raise SystemExit(1)

    seeded, skipped = seed_from_directory(get_table(), directory)
    for label in seeded:
        print(f"seed: wrote rate table {label}")
    for label in skipped:
        print(f"seed: already present, kept {label}")


if __name__ == "__main__":
    main()
