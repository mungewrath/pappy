# Pappy backend

FastAPI app (§2.2 of the design doc), run directly under `uvicorn` locally
and wrapped by Mangum in Lambda. No AWS imports in `pappy.api.app` itself —
the Lambda adapter (`pappy/api/handler.py`) is the only place Mangum is
imported, and it's never engaged locally.

## What's implemented

Phases 1–4 of §9: the calculation engine (gross pay + overtime premium
breakdown §5.4, Pub. 15-T federal withholding §5.3, FICA/WA PFML/WA Cares
withholding and employer accruals §5.1), the full core loop — `Employer`,
`Employee`, effective-dated W-4 elections, and the `PayRun` lifecycle
(create → auto-seeded from the default schedule → edit hours → finalize) —
and reminders (§6.6). Finalizing resolves the W-4 in effect on the pay date
and the current rate table for the tax year (`RATES#<year>`, seeded by
`pappy.repo.seed`), stores the complete computation on the run, and advances
the YTD wage-base accumulator in the same transaction (§4) — so a run can
never be finalized twice and wage caps can never double-count.

Phase 3 adds ReportLab pay stubs generated from finalized runs' stored
computations, including current and YTD earnings/withholdings and the explicit
overtime-premium breakdown. PDFs are stored in the private document bucket;
DynamoDB records retain their SHA-256 hashes and covered pay-run IDs. The API
supports generation, archive listing, and short-lived download URLs.

Phase 6 (tax season, numbers-first): historical entry via
`POST /payruns/employees/{id}/backfill` (weekly drafts across a past date
range, schedule-seeded or flat-hours) plus `POST /payruns/finalize-pending`
(locks drafts oldest-pay-date-first, stopping at the first failure — the only
order that keeps wage-base caps correct when history arrives late, which is
also enforced per-run at finalization). Year artifacts under `/tax-years/{year}`:
quarterly 1040-ES figures (`/1040-es`), the Schedule H worksheet with its
contributing runs (`/schedule-h`), W-2 box values (`/w2`), annual earnings
summaries (`/earnings-summary`), and the SSA EFW2 upload file
(`POST /efw2`, SSNs supplied transiently in the request body, never stored).
All of it reads finalized runs' *stored* computations — no report depends on
current rate tables.

Reminders: EventBridge Scheduler fires `pappy.scheduler.handler` per cadence;
each firing seeds the week's DRAFT pay runs (`WEEKLY_PAY`, §6.1),
materializes an idempotent `ReminderInstance` keyed by due date
(`REMINDER#<dueDate>#<rule>`), and emails it via SES (locally: logged).
Unacknowledged reminders stay visible via `GET /reminders` until acknowledged.

Not yet implemented: Adjustment entries and the later document generators for
FSA receipts, Schedule H, W-2/W-3, 1040-ES, and annual earnings summaries. The
tax-year endpoints already expose the numbers behind those future artifacts.

## Sending a test reminder

Three equivalent triggers — all run the same code path
(`pappy.services.scheduler_service.run_rule`) with the same idempotency:

1. **API** (works locally too):

   ```sh
   curl -X POST localhost:8000/reminders/test-send \
     -H 'content-type: application/json' -H "authorization: Bearer $TOKEN" \
     -d '{"rule": "WEEKLY_PAY", "fire_date": "2026-08-28"}'
   ```

   Body fields are all optional: `rule` (any `ReminderRule`),
   `fire_date`/`due_date`, `create_drafts` (default true), `send_email`
   (default true; set false while SES identities are unverified). There's a
   matching card in the frontend's **Reminders** tab.

2. **Lambda console**: open the function named by the
   `scheduler_function_name` Terraform output → **Test** → event `{}` runs
   the weekly loop for today. `{"rule": "SCHEDULE_H"}` fires any other rule;
   add `"fire_date": "YYYY-MM-DD"` to pin the date.

3. **EventBridge console**: create a one-off Schedule targeting that
   function with input `{"rule": "<RULE>"}` at any time.

Email routing is configured by `PAPPY_REMINDER_FROM_EMAIL`,
`PAPPY_REMINDER_TO_EMAIL`, and `PAPPY_MAILER` (`ses` in deployments, `log`
locally — logged mail shows up in `docker compose logs backend`). In SES
sandbox mode both addresses must be confirmed identities; Terraform creates
the verification requests on apply.

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
