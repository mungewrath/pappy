"""Maps repo- and calculation-layer exceptions to HTTP responses."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pappy.calc.fit import MissingW4Error
from pappy.mailer import MailerError
from pappy.repo.exceptions import AlreadyExistsError, InvalidStateError, NotFoundError


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(MailerError)
    async def _mailer(request: Request, exc: MailerError) -> JSONResponse:
        # Email delivery is upstream of this API (SES); surface it as a
        # bad gateway rather than pretending the reminder went out.
        return JSONResponse(status_code=502, content={"detail": str(exc)})
    @app.exception_handler(NotFoundError)
    async def _not_found(request: Request, exc: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AlreadyExistsError)
    async def _already_exists(request: Request, exc: AlreadyExistsError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(InvalidStateError)
    async def _invalid_state(request: Request, exc: InvalidStateError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(MissingW4Error)
    async def _missing_w4(request: Request, exc: MissingW4Error) -> JSONResponse:
        # A missing/invalid W-4 blocks finalization rather than silently
        # defaulting (§5.3) — a 409, since the fix is adding the prerequisite
        # election, not resubmitting the same request.
        return JSONResponse(status_code=409, content={"detail": str(exc)})
