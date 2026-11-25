"""Builds the configured OTP providers. Fail closed: an unset or unsupported
provider becomes the disabled provider, which delivers nothing (HTTP 503). No
code path substitutes the mock or console provider for a real one."""

from __future__ import annotations

from app.auth.otp import (
    ConsoleOtpProvider,
    DisabledOtpProvider,
    MockOtpProvider,
    OtpProvider,
    StagingFileOtpProvider,
)
from app.auth.smtp import SmtpOtpProvider, SmtpTransport, StdlibSmtpTransport
from app.core.config import Settings


def build_sms_provider(settings: Settings) -> OtpProvider:
    match settings.otp_provider:
        case "console":
            return ConsoleOtpProvider()
        case "mock":
            return MockOtpProvider()
        case "staging":
            return _staging(settings)
        case _:
            return DisabledOtpProvider()


def build_email_provider(
    settings: Settings, smtp_transport: SmtpTransport | None = None
) -> OtpProvider:
    match settings.otp_email_provider:
        case "mock":
            return MockOtpProvider()
        case "staging":
            return _staging(settings)
        case "smtp":
            # Settings validation guarantees these are present.
            assert settings.smtp_host and settings.smtp_from  # noqa: S101
            assert settings.smtp_username and settings.smtp_password  # noqa: S101
            transport = smtp_transport or StdlibSmtpTransport(
                host=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username,
                password=settings.smtp_password,
                starttls=settings.smtp_starttls,
                timeout=settings.smtp_timeout_seconds,
            )
            return SmtpOtpProvider(
                transport, sender=settings.smtp_from, timeout=settings.smtp_timeout_seconds
            )
        case _:
            return DisabledOtpProvider()


def _staging(settings: Settings) -> OtpProvider:
    assert settings.otp_staging_file  # noqa: S101 - validated in Settings
    return StagingFileOtpProvider(
        settings.otp_staging_file,
        settings.otp_staging_allowlist,
        ttl_seconds=settings.otp_ttl_seconds,
    )
