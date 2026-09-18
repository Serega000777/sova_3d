"""Error contract (docs/03 §1): machine code + user-safe message + details + trace_id."""

import logging
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger(__name__)


class APIError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class UnauthorizedError(APIError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(APIError):
    status_code = 403
    code = "forbidden"


class NotFoundError(APIError):
    status_code = 404
    code = "not_found"

    def __init__(self, resource: str, identifier: object) -> None:
        super().__init__(f"{resource} not found", {"resource": resource, "id": str(identifier)})


class ConflictError(APIError):
    status_code = 409
    code = "conflict"


class ValidationFailedError(APIError):
    status_code = 422
    code = "validation_failed"


class UnsupportedFormatError(APIError):
    status_code = 415
    code = "unsupported_format"


class PayloadTooLargeError(APIError):
    status_code = 413
    code = "payload_too_large"


def trace_id_of(request: Request) -> str:
    trace_id = getattr(request.state, "trace_id", None)
    return trace_id if isinstance(trace_id, str) else str(uuid.uuid4())


def _envelope(
    request: Request, status: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    body = {
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else {},
            "trace_id": trace_id_of(request),
        }
    }
    return JSONResponse(status_code=status, content=body)


def error_response(request: Request, exc: APIError) -> JSONResponse:
    """Render an APIError without raising — for outcomes that must be committed."""
    return _envelope(request, exc.status_code, exc.code, exc.message, exc.details)


def unhandled_error_response(request: Request) -> JSONResponse:
    """Anything that escapes is a bug: log it with the trace id, tell the client only the id."""
    trace_id = trace_id_of(request)
    log.exception("unhandled error [trace_id=%s] %s %s", trace_id, request.method, request.url)
    return _envelope(request, 500, "internal_error", "internal server error")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(request: Request, exc: APIError) -> JSONResponse:
        return _envelope(request, exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            request, 422, "validation_failed", "request validation failed", exc.errors()
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found"}.get(
            exc.status_code, "http_error"
        )
        return _envelope(request, exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Backstop for exceptions raised outside the middleware that normally catches them.
        return unhandled_error_response(request)
