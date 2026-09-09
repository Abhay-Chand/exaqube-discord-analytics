from __future__ import annotations

import json
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Every request gets a trace_id — from the `X-Trace-Id` header if the
    caller supplied one (so a frontend-generated id survives into backend
    logs), otherwise generated here. Stashed on request.state so route
    handlers, the error envelope, and the agent loop's log lines can all
    tag themselves with it, and returned in the response header so a client
    can correlate what it saw with what the server logged."""

    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("x-trace-id") or str(uuid.uuid4())
        request.state.trace_id = trace_id
        start = time.monotonic()
        response = await call_next(request)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        response.headers["X-Trace-Id"] = trace_id
        logging.getLogger("api").info(
            "request trace_id=%s method=%s path=%s status=%d elapsed_ms=%s",
            trace_id, request.method, request.url.path, response.status_code, elapsed_ms,
        )
        return response
