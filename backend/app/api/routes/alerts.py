"""/api/v1/alerts endpoints, as specified in contracts/openapi.yaml.

Every endpoint needs a valid session (401 first). Acknowledging and saving
preferences also need a `session` CSRF token, checked in a dependency before
anything is written. Only the caller's own alerts are read or changed."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi import status as http_status

from app.alerts.catalog import Severity, Source
from app.alerts.delivery import Channel
from app.alerts.schemas import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    AlertChannelsIn,
    AlertDeliveryListOut,
    AlertDeliveryOut,
    AlertOut,
    AlertPageOut,
    AlertPreferencesIn,
    AlertPreferencesOut,
)
from app.alerts.service import AlertService
from app.api.routes.auth import RequiredSession
from app.api.routes.brokers import csrf_session
from app.auth.service import SessionInfo
from app.core.errors import ApiError

router = APIRouter(prefix="/api/v1/alerts", tags=["alerts"])


def get_alerts(request: Request) -> AlertService:
    service: AlertService = request.app.state.alerts
    return service


Alerts = Annotated[AlertService, Depends(get_alerts)]

_READ_ERRORS: dict[int | str, dict[str, str]] = {
    401: {"description": "No valid session."},
    503: {"description": "Unavailable."},
}
_WRITE_ERRORS: dict[int | str, dict[str, str]] = {
    **_READ_ERRORS,
    403: {"description": "CSRF check failed."},
}


def _unique(values: list[str] | None, maximum: int) -> list[str]:
    values = values or []
    if len(values) > maximum or len(set(values)) != len(values):
        raise ApiError(400, "INVALID_REQUEST", "The request parameters are invalid.")
    return values


@router.get(
    "",
    response_model=AlertPageOut,
    operation_id="listAlerts",
    responses={400: {"description": "Invalid query parameters."}, **_READ_ERRORS},
)
async def list_alerts(
    session: RequiredSession,
    alerts: Alerts,
    severity: Annotated[list[Severity] | None, Query()] = None,
    source: Annotated[list[Source] | None, Query()] = None,
    status: Annotated[str, Query(pattern="^(all|unread)$")] = "all",
    cursor: Annotated[str | None, Query(min_length=1, max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> AlertPageOut:
    return await alerts.page(
        session.user_id,
        severities=_unique(severity, 3),  # type: ignore[arg-type]
        sources=_unique(source, 4),  # type: ignore[arg-type]
        unread=status == "unread",
        cursor=cursor,
        limit=limit,
    )


@router.get(
    "/preferences",
    response_model=AlertPreferencesOut,
    operation_id="getAlertPreferences",
    responses=_READ_ERRORS,
)
async def get_alert_preferences(session: RequiredSession, alerts: Alerts) -> AlertPreferencesOut:
    return await alerts.preferences(session.user_id)


@router.put(
    "/preferences",
    response_model=AlertPreferencesOut,
    operation_id="updateAlertPreferences",
    responses={400: {"description": "Malformed preferences."}, **_WRITE_ERRORS},
)
async def update_alert_preferences(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    alerts: Alerts,
    body: Annotated[AlertPreferencesIn, Body()],
) -> AlertPreferencesOut:
    return await alerts.save_preferences(session.user_id, body)


@router.post(
    "/{alertId}/ack",
    response_model=AlertOut,
    operation_id="acknowledgeAlert",
    responses={404: {"description": "No such alert for the caller."}, **_WRITE_ERRORS},
)
async def acknowledge_alert(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    alerts: Alerts,
    alert_id: Annotated[str, Path(alias="alertId", min_length=1, max_length=64)],
) -> AlertOut:
    return await alerts.acknowledge(session.user_id, alert_id)


@router.put(
    "/channels",
    response_model=AlertPreferencesOut,
    operation_id="updateAlertChannels",
    responses={409: {"description": "Channel unavailable."}, **_WRITE_ERRORS},
)
async def update_alert_channels(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    alerts: Alerts,
    body: Annotated[AlertChannelsIn, Body()],
) -> AlertPreferencesOut:
    return await alerts.save_channels(session.user_id, body)


@router.post(
    "/channels/{channel}/test",
    response_model=AlertDeliveryOut,
    status_code=http_status.HTTP_202_ACCEPTED,
    operation_id="sendAlertChannelTest",
    responses={409: {"description": "Channel unavailable."}, **_WRITE_ERRORS},
)
async def send_alert_channel_test(
    session: Annotated[SessionInfo, Depends(csrf_session)],
    alerts: Alerts,
    channel: Annotated[Channel, Path()],
) -> AlertDeliveryOut:
    return await alerts._require_delivery().queue_test(session.user_id, channel)


@router.get(
    "/deliveries",
    response_model=AlertDeliveryListOut,
    operation_id="listAlertDeliveries",
    responses=_READ_ERRORS,
)
async def list_alert_deliveries(session: RequiredSession, alerts: Alerts) -> AlertDeliveryListOut:
    return await alerts._require_delivery().recent(session.user_id)
