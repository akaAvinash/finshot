"""/api/v1/reports endpoints, as specified in contracts/openapi.yaml.

Read-only: both need a valid session and no CSRF token. Paper ledger only."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response

from app.api.routes.auth import RequiredSession
from app.reports.schemas import ReportEmptyOut, ReportReadyOut
from app.reports.service import CSV_FILENAME, ReportService

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def get_reports(request: Request) -> ReportService:
    service: ReportService = request.app.state.reports
    return service


Reports = Annotated[ReportService, Depends(get_reports)]
From = Annotated[date | None, Query(alias="from")]
To = Annotated[date | None, Query()]

_ERRORS: dict[int | str, dict[str, str]] = {
    400: {"description": "A date is malformed, or `from` is after `to`."},
    401: {"description": "No valid session."},
    503: {"description": "Unavailable."},
}


@router.get(
    "/paper",
    response_model=ReportReadyOut | ReportEmptyOut,
    operation_id="getPaperReport",
    responses=_ERRORS,
)
async def get_paper_report(
    session: RequiredSession, reports: Reports, from_: From = None, to: To = None
) -> ReportReadyOut | ReportEmptyOut:
    return await reports.paper_report(session.user_id, from_, to)


@router.get(
    "/paper/trades.csv",
    response_class=Response,
    operation_id="exportPaperTrades",
    responses={
        200: {"content": {"text/csv": {"schema": {"type": "string"}}}},
        **_ERRORS,
    },
)
async def export_paper_trades(
    session: RequiredSession, reports: Reports, from_: From = None, to: To = None
) -> Response:
    body = await reports.paper_trades_csv(session.user_id, from_, to)
    return Response(
        content=body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{CSV_FILENAME}"'},
    )
