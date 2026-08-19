# Pappy backend

FastAPI app (§2.2 of the design doc), run directly under `uvicorn` locally
and wrapped by Mangum in Lambda. No AWS imports in the app itself — the
Lambda adapter (`pappy/api/handler.py`) is the only AWS-specific bit, and it's
never engaged locally.

## Local development

```sh
uv sync
uv run uvicorn pappy.api.app:app --reload --port 8000
```

`GET http://localhost:8000/hello` should return
`{"message": "Hello from Pappy!"}`. CORS is open to the Vite dev server
origin (`http://localhost:5173`) for local development only.

## Tests / lint / types

```sh
uv run pytest
uv run ruff check .
uv run mypy pappy
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
