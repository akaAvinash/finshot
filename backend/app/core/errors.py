"""Error response shape shared by all endpoints.

Matches the error schema in contracts/openapi.yaml: {"code", "message"} with
UPPER_SNAKE_CASE codes, plus an optional camelCase "requestId" and, for 429,
"retryAfterSeconds". An error may also carry extra fields (`extra`), such as
the Trade Controls `fieldErrors`."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raise from a route or service to return a contract-shaped error."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        *,
        retry_after_seconds: int | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after_seconds = retry_after_seconds
        self.extra = extra


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    retry_after_seconds: int | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if extra:
        body.update(extra)
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["requestId"] = request_id
    headers: dict[str, str] = {}
    if retry_after_seconds is not None:
        body["retryAfterSeconds"] = retry_after_seconds
        headers["Retry-After"] = str(retry_after_seconds)
    return JSONResponse(status_code=status_code, content=body, headers=headers)
