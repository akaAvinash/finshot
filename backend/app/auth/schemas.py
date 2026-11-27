"""Request/response models. Field names are camelCase on the wire, matching
contracts/openapi.yaml."""

from __future__ import annotations

import unicodedata
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
)
from pydantic.alias_generators import to_camel

PHONE_PATTERN = r"^\+91[6-9][0-9]{9}$"


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class _Strict(_Wire):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class OtpRequest(_Strict):
    phone: str = Field(pattern=PHONE_PATTERN)
    channel: Literal["sms", "email"] = "sms"


class OtpChallengeOut(_Wire):
    challenge_id: uuid.UUID
    channel: Literal["sms", "email"]
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
    totp_enabled: bool


class SessionExpiryOut(_Wire):
    idle_expires_at: datetime
    expires_at: datetime
    step_up_until: datetime | None
    # Only a tester session reports its access; a regular session leaves the
    # field out, so the existing response shape does not change.
    access: Literal["tester"] | None = None

    @model_serializer(mode="wrap")
    def _drop_empty_access(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for key in ("access",):
            if data.get(key) is None:
                data.pop(key, None)
        return data


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


class TotpCodeIn(_Strict):
    code: str = Field(pattern=r"^[0-9]{6}$")


class TotpEnrollmentOut(_Wire):
    secret: str
    otpauth_uri: str
    expires_at: datetime


class RecoveryCodesOut(_Wire):
    codes: list[str]
    created_at: datetime


class StepUpResultOut(_Wire):
    totp_enabled: Literal[True] = True
    step_up_until: datetime


Timezone = Literal["Asia/Kolkata", "UTC"]


def _clean_display_name(value: str) -> str:
    """Trim, then require 1 to 48 characters with no control characters."""
    name = value.strip()
    if not 1 <= len(name) <= 48:
        raise ValueError("display name must be 1 to 48 characters")
    if any(unicodedata.category(ch) == "Cc" for ch in name):
        raise ValueError("display name must not contain control characters")
    return name


class SettingsProfileOut(_Wire):
    display_name: str | None
    timezone: Timezone
    phone_masked: str


class SettingsProfileIn(_Strict):
    display_name: Annotated[str, Field(max_length=200)]
    timezone: Timezone

    @field_validator("display_name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_display_name(value)


RECOVERY_CODE_PATTERN = r"^[A-Z2-7]{5}-[A-Z2-7]{5}$"


class RecoveryLogin(_Strict):
    phone: str = Field(pattern=PHONE_PATTERN)
    recovery_code: str = Field(pattern=RECOVERY_CODE_PATTERN)


class TesterLogin(_Strict):
    phone: str = Field(pattern=PHONE_PATTERN)
    invite_code: str = Field(pattern=r"^[A-Za-z0-9_-]{22}$")


class TotpLogin(_Strict):
    phone: str = Field(pattern=PHONE_PATTERN)
    code: str = Field(pattern=r"^[0-9]{6}$")
