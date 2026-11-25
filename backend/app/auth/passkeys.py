"""Passkey (WebAuthn) authentication: the interface only.

Nothing implements it yet and no endpoint uses it. It exists so a WebAuthn
module can be added later without touching the OTP, session or step-up code:
the module would verify a passkey assertion and return the user's id, and the
caller would then start a session or open a step-up window exactly as the OTP
and TOTP paths do. Until then the null implementation reports itself
unavailable and never authenticates anyone."""

from __future__ import annotations

import uuid
from typing import Protocol


class PasskeyAuthenticator(Protocol):
    @property
    def available(self) -> bool: ...

    async def begin_registration(self, user_id: uuid.UUID) -> dict[str, object]: ...

    async def finish_registration(
        self, user_id: uuid.UUID, credential: dict[str, object]
    ) -> None: ...

    async def begin_authentication(self) -> dict[str, object]: ...

    async def finish_authentication(self, assertion: dict[str, object]) -> uuid.UUID | None:
        """The authenticated user's id, or None when the assertion is invalid."""


class UnavailablePasskeys:
    available = False

    async def begin_registration(self, user_id: uuid.UUID) -> dict[str, object]:
        raise NotImplementedError("passkeys are not implemented")

    async def finish_registration(self, user_id: uuid.UUID, credential: dict[str, object]) -> None:
        raise NotImplementedError("passkeys are not implemented")

    async def begin_authentication(self) -> dict[str, object]:
        raise NotImplementedError("passkeys are not implemented")

    async def finish_authentication(self, assertion: dict[str, object]) -> uuid.UUID | None:
        return None
