from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("api")


def envelope(code: str, message: str, trace_id: str | None, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "trace_id": trace_id, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=422,
            content=envelope("VALIDATION_ERROR", "Request failed validation.", trace_id, {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exc_handler(request: Request, exc: StarletteHTTPException):
        trace_id = getattr(request.state, "trace_id", None)
        return JSONResponse(
            status_code=exc.status_code,
            content=envelope("HTTP_ERROR", str(exc.detail), trace_id),
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "trace_id", None)
        # Never let a raw traceback reach the wire. Full detail goes to the
        # structured log (with the same trace_id), the client gets a stable
        # 500 envelope it can actually parse.
        logger.exception("unhandled_exception trace_id=%s", trace_id)
        return JSONResponse(
            status_code=500,
            content=envelope("INTERNAL_ERROR", "An unexpected error occurred.", trace_id),
        )
