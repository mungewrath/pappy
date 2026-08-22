"""Employer CRUD endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from pappy.api.deps import get_table
from pappy.models.employer import Employer, EmployerCreate, EmployerUpdate
from pappy.services import employer_service

router = APIRouter(prefix="/employers", tags=["employers"])

TableDep = Annotated[Any, Depends(get_table)]


@router.post("", response_model=Employer, status_code=201)
def create_employer(data: EmployerCreate, table: TableDep) -> Employer:
    return employer_service.create_employer(table, data)


@router.get("/{employer_id}", response_model=Employer)
def get_employer(employer_id: str, table: TableDep) -> Employer:
    return employer_service.get_employer(table, employer_id)


@router.patch("/{employer_id}", response_model=Employer)
def update_employer(employer_id: str, data: EmployerUpdate, table: TableDep) -> Employer:
    return employer_service.update_employer(table, employer_id, data)
