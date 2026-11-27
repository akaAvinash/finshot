"""/api/v1/settings/* endpoints, as specified in contracts/openapi.yaml.

A valid session is needed (401 first). Saving also needs a `session` CSRF
token, checked in a dependency before anything is written."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request, status

from app.api.routes.auth import Auth, RequiredSession, ensure_stepped_up
from app.api.routes.brokers import csrf_session
from app.auth.otp import mask_phone
from app.auth.phone_change import PhoneChangeService
from app.auth.schemas import (
    PhoneChangeChallengeOut,
    PhoneChangeConfirmIn,
    PhoneChangeIn,
    SettingsProfileIn,
    SettingsProfileOut,
    Timezone,
)
from app.auth.service import SessionInfo
from app.paper import controls as tc
from app.paper.service import PaperService
from app.retention.schemas import DataRetentionIn, DataRetentionOut
from app.retention.service import RetentionService

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

CsrfSession = Annotated[SessionInfo, Depends(csrf_session)]


def _out(info: SessionInfo, name: str | None, timezone: str) -> SettingsProfileOut:
    return SettingsProfileOut(
        display_name=name,
        timezone=cast(Timezone, timezone),
        phone_masked=mask_phone(info.phone_e164),
    )


@router.get("/profile", response_model=SettingsProfileOut, operation_id="getSettingsProfile")
async def get_profile(auth: Auth, session: RequiredSession) -> SettingsProfileOut:
    name, timezone = await auth.get_profile(session)
    return _out(session, name, timezone)


@router.put("/profile", response_model=SettingsProfileOut, operation_id="updateSettingsProfile")
async def update_profile(
    body: SettingsProfileIn, auth: Auth, session: CsrfSession
) -> SettingsProfileOut:
    name, timezone = await auth.update_profile(
        session, display_name=body.display_name, timezone=body.timezone
    )
    return _out(session, name, timezone)


def get_paper(request: Request) -> PaperService:
    service: PaperService = request.app.state.paper
    return service


Paper = Annotated[PaperService, Depends(get_paper)]


async def stepped_up_write_session(
    request: Request, auth: Auth, session: RequiredSession
) -> SessionInfo:
    """401, 403 TOTP_SETUP_REQUIRED, 403 CSRF_FAILED, 403 STEP_UP_REQUIRED, in
    this order, before the body is looked at."""
    auth.enforce_csrf(request, session)
    ensure_stepped_up(auth, session)
    return session


TradeControlsSaveSession = Annotated[SessionInfo, Depends(stepped_up_write_session)]
SteppedUpWriteSession = TradeControlsSaveSession


@router.get(
    "/trade-controls",
    response_model=tc.TradeControlsSettingsOut,
    operation_id="getTradeControls",
)
async def get_trade_controls(session: RequiredSession, paper: Paper) -> tc.TradeControlsSettingsOut:
    return await paper.trade_controls(session.user_id)


@router.put(
    "/trade-controls",
    response_model=tc.TradeControlsSettingsOut,
    operation_id="updateTradeControls",
)
async def update_trade_controls(
    body: tc.TradeControlsUpdateIn, session: TradeControlsSaveSession, paper: Paper
) -> tc.TradeControlsSettingsOut:
    return await paper.update_trade_controls(session.user_id, body)


@router.get(
    "/trade-controls/history",
    response_model=tc.TradeControlsHistoryOut,
    operation_id="getTradeControlsHistory",
)
async def get_trade_controls_history(
    session: RequiredSession, paper: Paper
) -> tc.TradeControlsHistoryOut:
    return await paper.trade_controls_history(session.user_id)


def get_phone_change(request: Request) -> PhoneChangeService:
    service: PhoneChangeService = request.app.state.phone_change
    return service


PhoneChange = Annotated[PhoneChangeService, Depends(get_phone_change)]


@router.post(
    "/phone/change",
    response_model=PhoneChangeChallengeOut,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="requestPhoneChange",
)
async def request_phone_change(
    body: PhoneChangeIn, request: Request, session: SteppedUpWriteSession, service: PhoneChange
) -> PhoneChangeChallengeOut:
    challenge_id, expires_at, resend_at, masked = await service.request(
        request=request, session=session, new_phone=body.new_phone
    )
    return PhoneChangeChallengeOut(
        challenge_id=challenge_id,
        expires_at=expires_at,
        resend_available_at=resend_at,
        destination_masked=masked,
    )


@router.post(
    "/phone/change/confirm",
    response_model=SettingsProfileOut,
    operation_id="confirmPhoneChange",
)
async def confirm_phone_change(
    body: PhoneChangeConfirmIn,
    request: Request,
    session: SteppedUpWriteSession,
    service: PhoneChange,
    auth: Auth,
) -> SettingsProfileOut:
    await service.confirm(
        request=request, session=session, challenge_id=body.challenge_id, code=body.code
    )
    name, timezone = await auth.get_profile(session)
    return SettingsProfileOut(
        display_name=name,
        timezone=cast(Timezone, timezone),
        phone_masked=mask_phone(await auth.current_phone(session.user_id)),
    )


def get_retention(request: Request) -> RetentionService:
    service: RetentionService = request.app.state.retention
    return service


Retention = Annotated[RetentionService, Depends(get_retention)]


@router.get("/data-retention", response_model=DataRetentionOut, operation_id="getDataRetention")
async def get_data_retention(session: RequiredSession, retention: Retention) -> DataRetentionOut:
    return await retention.get(session.user_id)


@router.put("/data-retention", response_model=DataRetentionOut, operation_id="updateDataRetention")
async def update_data_retention(
    body: DataRetentionIn, session: SteppedUpWriteSession, retention: Retention
) -> DataRetentionOut:
    return await retention.update(session.user_id, body.retention_days)
