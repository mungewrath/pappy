# Pappy backend

FastAPI app (§2.2 of the design doc), run directly under `uvicorn` locally
and wrapped by Mangum in Lambda. No AWS imports in `pappy.api.app` itself —
the Lambda adapter (`pappy/api/handler.py`) is the only place Mangum is
imported, and it's never engaged locally.

## What's implemented

Phase 2's core CRUD loop (§9): `Employer`, `Employee`, and `PayRun` (draft
lifecycle: create → edit hours → finalize), backed by the single-table
DynamoDB layout in §4. Gross pay and the overtime-premium breakdown (§5.4)
are computed on every hour-line change. **Withholding, net pay, and
employer tax accruals are not implemented yet** — that requires the Pub.
15-T percentage-method engine and versioned rate tables (§5.1–§5.3), which
is its own pass (Phase 1 in §9). A finalized `PayRun` today only locks
gross pay and a `rate_table_version` placeholder.

## Local development

The API talks to DynamoDB through `pappy.repo.table`, which is configured
by environment variables so the same code runs against real AWS, DynamoDB
Local, or (in tests) `moto`. For local dev, run DynamoDB Local:

```sh
docker run -d --rm -p 8500:8000 amazon/dynamodb-local

export PAPPY_DYNAMODB_ENDPOINT_URL=http://localhost:8500
export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_REGION=us-west-2

uv sync
uv run python -c "from pappy.repo.table import create_table_if_not_exists; create_table_if_not_exists()"
uv run uvicorn pappy.api.app:app --reload --port 8000
```

`GET http://localhost:8000/hello` should return
`{"message": "Hello from Pappy!"}`. Try the CRUD flow, e.g.:

```sh
curl -X POST localhost:8000/employers -H 'content-type: application/json' -d '{
  "legal_name": "Jane Doe", "ein": "12-3456789",
  "address": {"line1": "1 Main St", "city": "Seattle", "state": "WA", "zip_code": "98101"}
}'
```

CORS is open to the Vite dev server origin (`http://localhost:5173`) for
local development only.

If you don't have Docker, you can skip DynamoDB Local entirely and just run
the test suite (below) — it exercises the exact same repo/service/API code
against an in-memory fake table via `moto`, with no setup required.

## Tests / lint / types

```sh
uv run pytest        # unit + repo + API tests, no AWS/Docker required (moto)
uv run ruff check .
uv run mypy pappy tests
```

## Packaging for Lambda

```sh
./build.sh
```

Exports pinned dependencies, installs them for `linux/aarch64` (Python 3.13),
adds the application code, and zips the result to `dist/api-lambda.zip`. This
is the artifact Terraform's `api` module expects (via an object key/version
variable) — packaging happens outside `terraform plan`/`apply` per §2.4 of the
design doc.
