"""FastAPI exception handlers mapping backend errors to unified JSON responses."""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .base import VisaLaneError
from .logging import log_structured_error


def setup_exception_handlers(app: FastAPI) -> None:
    """Register unified exception handlers on FastAPI application."""

    @app.exception_handler(VisaLaneError)
    async def visalane_error_handler(request: Request, exc: VisaLaneError) -> JSONResponse:
        log_structured_error(
            exc=exc,
            request_id=exc.request_id,
            endpoint=str(request.url.path),
        )
        return JSONResponse(
            status_code=exc.http_status,
            content=exc.to_dict(),
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Wrap in base error
        base_err = VisaLaneError(
            message=str(exc) or "Internal server error",
            user_message="An unexpected error occurred. Please try again shortly.",
        )
        log_structured_error(
            exc=exc,
            request_id=base_err.request_id,
            endpoint=str(request.url.path),
        )
        return JSONResponse(
            status_code=500,
            content=base_err.to_dict(),
        )
