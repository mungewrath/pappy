"""Employer profile endpoints, scoped to the authenticated caller (§7.1).

The employer id is the JWT access token's `sub` claim — the client never
supplies it. `POST /employers` is an idempotent get-or-create so re-running
onboarding from a new browser is safe.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, status

from pappy.api.deps import EmployerIdDep, get_table
from pappy.models.employer import Employer, EmployerCreate, EmployerUpdate
from pappy.services import employer_service

router = APIRouter(prefix="/employers", tags=["employers"])

TableDep = Annotated[Any, Depends(get_table)]


@router.post("", response_model=Employer, status_code=201)
def create_employer(
    data: EmployerCreate, response: Response, table: TableDep, employer_id: EmployerIdDep
) -> Employer:
    """Create (or return, unchanged, if it already exists) the caller's profile."""
    employer, created = employer_service.create_employer(table, employer_id, data)
    if not created:
        response.status_code = status.HTTP_200_OK
    return employer


@router.get("", response_model=Employer)
def get_employer(table: TableDep, employer_id: EmployerIdDep) -> Employer:
    return employer_service.get_employer(table, employer_id)


@router.patch("", response_model=Employer)
def update_employer(data: EmployerUpdate, table: TableDep, employer_id: EmployerIdDep) -> Employer:
    return employer_service.update_employer(table, employer_id, data)
