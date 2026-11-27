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

import asyncio
import smtplib
from collections.abc import Callable
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Literal, Protocol

import structlog

from app.auth.otp import mask_destination
from app.auth.smtp import SmtpTransport, StdlibSmtpTransport
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


def _header(value: str) -> str:
    """One line, no control characters: a header value cannot start another header."""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())


class SmtpNotificationProvider:
    """Real email through the owner's own mailbox over SMTP with STARTTLS.
    Credentials live only in the transport (from the server environment). A
    failure raises NotificationDeliveryError with a fixed reason: never the
    server's reply, the credentials or the destination."""

    configured = True
    simulated = False

    def __init__(
        self,
        transport: SmtpTransport,
        *,
        sender: str,
        timeout: float,
        service_name: str = "Tradeo",
        run_in_thread: Callable[..., object] = asyncio.to_thread,
    ) -> None:
        self._transport = transport
        self._sender = sender
        self._timeout = timeout
        self._service = service_name
        self._run = run_in_thread

    async def send(self, notification: Notification) -> None:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = notification.destination
        message["Subject"] = _header(f"[{self._service}] {notification.title}")[:200]
        message.set_content(f"{notification.body}\n\nOpen your alerts: {notification.link}\n")
        try:
            # The thread cannot be cancelled, so the wait is bounded here as well
            # as by the socket timeout inside the transport.
            await asyncio.wait_for(
                self._run(self._transport.send, message),  # type: ignore[arg-type]
                timeout=self._timeout + 5,
            )
        except TimeoutError as exc:
            raise NotificationDeliveryError("smtp timed out") from exc
        except (smtplib.SMTPException, OSError) as exc:
            raise NotificationDeliveryError(f"smtp failed ({type(exc).__name__})") from exc


def build_providers(settings: Settings) -> dict[Channel, NotificationProvider]:
    def one(name: str) -> NotificationProvider:
        return LogNotificationProvider() if name == "log" else DisabledNotificationProvider()

    email: NotificationProvider
    if settings.notify_email_provider == "smtp":
        # Settings guarantee the mailbox details and STARTTLS are present.
        assert settings.smtp_host and settings.smtp_from  # noqa: S101
        assert settings.smtp_username and settings.smtp_password  # noqa: S101
        email = SmtpNotificationProvider(
            StdlibSmtpTransport(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                starttls=True,
                timeout=settings.smtp_timeout_seconds,
            ),
            sender=settings.smtp_from,
            timeout=settings.smtp_timeout_seconds,
        )
    else:
        email = one(settings.notify_email_provider)

    return {
        "email": email,
        "sms": one(settings.notify_sms_provider),
        "push": one(settings.notify_push_provider),
    }
