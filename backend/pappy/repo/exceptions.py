"""Repo-layer errors, translated to HTTP responses at the API boundary."""

from __future__ import annotations


class RepoError(Exception):
    """Base class for all repo-layer errors."""


class NotFoundError(RepoError):
    def __init__(self, entity: str, key: str) -> None:
        super().__init__(f"{entity} not found: {key}")
        self.entity = entity
        self.key = key


class AlreadyExistsError(RepoError):
    def __init__(self, entity: str, key: str) -> None:
        super().__init__(f"{entity} already exists: {key}")
        self.entity = entity
        self.key = key


class InvalidStateError(RepoError):
    """Raised when an operation is attempted against an entity in the wrong state.

    e.g. editing hour lines on a FINALIZED PayRun (design-doc.md §3.2).
    """
