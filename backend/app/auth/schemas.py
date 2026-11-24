"""Request/response models. Field names are camelCase on the wire, matching
contracts/openapi.yaml."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

PHONE_PATTERN = r"^\+91[6-9][0-9]{9}$"


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Strict(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class OtpRequest(_Strict):
    phone: str = Field(pattern=PHONE_PATTERN)


class OtpChallengeOut(_Wire):
    challenge_id: uuid.UUID
    expires_at: datetime
    resend_available_at: datetime


class OtpVerify(_Strict):
    challenge_id: uuid.UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class CsrfTokenOut(_Wire):
    csrf_token: str
    context: Literal["pre_login", "session"]
    expires_at: datetime


class AuthUserOut(_Wire):
    id: uuid.UUID
    phone_masked: str
    display_name: str | None
    created_at: datetime


class SessionExpiryOut(_Wire):
    idle_expires_at: datetime
    expires_at: datetime


class AuthSessionOut(_Wire):
    user: AuthUserOut
    session: SessionExpiryOut


class OtpVerifyResponse(AuthSessionOut):
    csrf_token: str


class SessionSummaryOut(_Wire):
    id: uuid.UUID
    device_label: str | None
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class SessionListOut(_Wire):
    sessions: list[SessionSummaryOut]
