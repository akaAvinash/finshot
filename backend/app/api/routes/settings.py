"""/api/v1/settings/* endpoints, as specified in contracts/openapi.yaml.

A valid session is needed (401 first). Saving also needs a `session` CSRF
token, checked in a dependency before anything is written."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends

from app.api.routes.auth import Auth, RequiredSession
from app.api.routes.brokers import csrf_session
from app.auth.otp import mask_phone
from app.auth.schemas import SettingsProfileIn, SettingsProfileOut, Timezone
from app.auth.service import SessionInfo

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
