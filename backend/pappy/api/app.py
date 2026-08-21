"""FastAPI application.

This module defines the API surface. It has no AWS-specific imports so it can
run directly under `uvicorn` for local development (see README) or be wrapped
by Mangum for Lambda (see `pappy.api.handler`).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pappy.api.errors import register_error_handlers
from pappy.api.routers import employees, employers, payruns

app = FastAPI(title="Pappy API", version="0.1.0")

# Local dev only: allow the Vite dev server to call this API directly.
# Once deployed, the SPA and API are same-origin behind CloudFront (or the
# API Gateway domain is added explicitly) and this can be tightened.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

register_error_handlers(app)
app.include_router(employers.router)
app.include_router(employees.router)
app.include_router(payruns.router)


class HelloResponse(BaseModel):
    message: str


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check — used by nothing yet, but cheap to have."""
    return {"status": "ok"}


@app.get("/hello", response_model=HelloResponse)
def hello() -> HelloResponse:
    """Hello-world endpoint proving the API Gateway -> Lambda -> FastAPI path."""
    return HelloResponse(message="Hello from Pappy!")
