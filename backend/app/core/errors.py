"""Error response shape shared by all endpoints.

Matches the error schema in contracts/openapi.yaml: {"code", "message"} with
UPPER_SNAKE_CASE codes, plus an optional camelCase "requestId"."""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


def error_response(request: Request, status_code: int, code: str, message: str) -> JSONResponse:
    body: dict[str, str] = {"code": code, "message": message}
    request_id = getattr(request.state, "request_id", None)
    if request_id:
        body["requestId"] = request_id
    return JSONResponse(status_code=status_code, content=body)
