"""/api/v1/settings/* endpoints, as specified in contracts/openapi.yaml.

A valid session is needed (401 first). Saving also needs a `session` CSRF
token, checked in a dependency before anything is written."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Request

from app.api.routes.auth import Auth, RequiredSession, ensure_stepped_up
from app.api.routes.brokers import csrf_session
from app.auth.otp import mask_phone
from app.auth.schemas import SettingsProfileIn, SettingsProfileOut, Timezone
from app.auth.service import SessionInfo
from app.paper import controls as tc
from app.paper.service import PaperService

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


async def trade_controls_save_session(
    request: Request, auth: Auth, session: RequiredSession
) -> SessionInfo:
    """401, 403 TOTP_SETUP_REQUIRED, 403 CSRF_FAILED, 403 STEP_UP_REQUIRED, in
    this order, before the body is looked at."""
    auth.enforce_csrf(request, session)
    ensure_stepped_up(auth, session)
    return session


TradeControlsSaveSession = Annotated[SessionInfo, Depends(trade_controls_save_session)]


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
