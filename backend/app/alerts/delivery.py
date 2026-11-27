"""Provider-neutral alert delivery by email, SMS and push (contract 0.13.0).

A `NotificationProvider` sends one `Notification` to one destination. Only
two exist: `DisabledNotificationProvider` (the channel is unavailable) and
`LogNotificationProvider`, a *simulated* provider that writes a masked log
line and sends nothing. A real provider (SMTP, an SMS gateway, Web Push or
FCM) implements the same protocol once the owner picks one and supplies
credentials; nothing else changes.

Destinations are resolved when sending, never stored in full: email is the
address on the account's active invite, SMS the account's phone number, push
has no registered device yet (NO_DESTINATION)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import structlog

from app.auth.otp import mask_destination
from app.core.config import Settings

logger = structlog.get_logger(__name__)

Channel = Literal["email", "sms", "push"]
CHANNELS: tuple[Channel, ...] = ("email", "sms", "push")


class NotificationDeliveryError(Exception):
    """The provider did not accept the message. Never include the destination."""


@dataclass(frozen=True)
class Notification:
    delivery_id: str
    channel: Channel
    destination: str
    title: str
    body: str
    link: str


class NotificationProvider(Protocol):
    @property
    def configured(self) -> bool: ...

    @property
    def simulated(self) -> bool: ...

    async def send(self, notification: Notification) -> None: ...


class DisabledNotificationProvider:
    configured = False
    simulated = False

    async def send(self, notification: Notification) -> None:
        raise NotificationDeliveryError("no provider is configured for this channel")


class LogNotificationProvider:
    """Simulated: logs the channel, a masked destination and the title.
    Sends nothing anywhere. Refused in production by settings."""

    configured = True
    simulated = True

    async def send(self, notification: Notification) -> None:
        logger.info(
            "notification_simulated",
            channel=notification.channel,
            destination=mask_destination(notification.destination),
            delivery_id=notification.delivery_id,
            title=notification.title,
        )


def build_providers(settings: Settings) -> dict[Channel, NotificationProvider]:
    def one(name: str) -> NotificationProvider:
        return LogNotificationProvider() if name == "log" else DisabledNotificationProvider()

    return {
        "email": one(settings.notify_email_provider),
        "sms": one(settings.notify_sms_provider),
        "push": one(settings.notify_push_provider),
    }
