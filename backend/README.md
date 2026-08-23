# Pappy backend

FastAPI app (§2.2 of the design doc), run directly under `uvicorn` locally
and wrapped by Mangum in Lambda. No AWS imports in `pappy.api.app` itself —
the Lambda adapter (`pappy/api/handler.py`) is the only place Mangum is
imported, and it's never engaged locally.

## What's implemented

Phases 1–2 of §9: the calculation engine (gross pay + overtime premium
breakdown §5.4, Pub. 15-T federal withholding §5.3, FICA/WA PFML/WA Cares
withholding and employer accruals §5.1) plus the full core loop — `Employer`,
`Employee`, effective-dated W-4 elections, and the `PayRun` lifecycle
(create → auto-seeded from the default schedule → edit hours → finalize).
Finalizing resolves the W-4 in effect on the pay date and the current rate
table for the tax year (`RATES#<year>`, seeded by `pappy.repo.seed`), stores
the complete computation on the run, and advances the YTD wage-base
accumulator in the same transaction (§4) — so a run can never be finalized
twice and wage caps can never double-count.

Not yet implemented: Adjustment entries, document generation (Phase 3+),
reminders (Phase 4).

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
PAPPY_RATES_DIR=../rates uv run python -m pappy.repo.seed
uv run uvicorn pappy.api.app:app --reload --port 8000
```

The seed step loads every `rates/<year>.json` into `RATES#<year>` — without
it, finalization fails with a 404 for that tax year (§5.2: rates are data,
and missing data must block, not default). It is idempotent; re-run it after
adding a year or version.

`GET http://localhost:8000/hello` should return
`{"message": "Hello from Pappy!"}`. Try the CRUD flow, e.g.:

```sh
# Every data endpoint derives employerId from the JWT `sub` claim (§7.1) and
# 401s without a token; locally the Bearer payload is decoded unverified
# (production tokens are validated by API Gateway's JWT authorizer).
TOKEN="header.$(printf '{"sub":"local-dev-user"}' | base64 | tr -d '=' | tr '/+' '_-').sig"
curl -X POST localhost:8000/employers -H 'content-type: application/json' \
  -H "authorization: Bearer $TOKEN" -d '{
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
