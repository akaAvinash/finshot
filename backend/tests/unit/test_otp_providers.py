"""OTP providers, provider selection and the production guards (no services needed)."""

from __future__ import annotations

import asyncio
import json
import smtplib
import stat
from email.message import EmailMessage
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.auth import totp
from app.auth.admin import AdminError, staging_code, validate_phone
from app.auth.otp import (
    DisabledOtpProvider,
    MockOtpProvider,
    OtpDeliveryError,
    StagingFileOtpProvider,
    mask_destination,
    read_staging_codes,
)
from app.auth.providers import build_email_provider, build_sms_provider
from app.auth.smtp import SmtpOtpProvider
from tests.conftest import SettingsFactory

PHONE = "+919876543210"


def run(coro):  # type: ignore[no-untyped-def]
    return asyncio.run(coro)


def test_masking_hides_the_middle() -> None:
    assert mask_destination(PHONE) == "+91******3210"
    assert mask_destination("alice@example.com") == "a***@example.com"


def test_mock_provider_records_and_is_fixed() -> None:
    mock = MockOtpProvider()
    assert mock.new_code() == "123456"
    run(mock.deliver(PHONE, "123456"))
    assert mock.sent == [(PHONE, "123456")]


def test_disabled_provider_always_fails() -> None:
    with pytest.raises(OtpDeliveryError):
        run(DisabledOtpProvider().deliver(PHONE, "123456"))


def test_staging_provider_writes_private_file_for_allowlisted_numbers(tmp_path: Path) -> None:
    path = tmp_path / "otp.json"
    now = [1000.0]
    provider = StagingFileOtpProvider(
        str(path), [PHONE], ttl_seconds=300, clock_seconds=lambda: now[0]
    )
    run(provider.deliver(PHONE, "654321"))
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text())[PHONE] == {"code": "654321", "expiresAt": 1300.0}
    assert read_staging_codes(path, now=1200.0)[PHONE]["code"] == "654321"
    assert read_staging_codes(path, now=1301.0) == {}


def test_staging_provider_refuses_numbers_off_the_allowlist(tmp_path: Path) -> None:
    provider = StagingFileOtpProvider(str(tmp_path / "otp.json"), [PHONE])
    with pytest.raises(OtpDeliveryError, match="allowlist"):
        run(provider.deliver("+918765432109", "111111"))
    assert not (tmp_path / "otp.json").exists()


def test_staging_provider_unwritable_path_is_a_delivery_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    provider = StagingFileOtpProvider(str(blocker / "otp.json"), [PHONE])
    with pytest.raises(OtpDeliveryError):
        run(provider.deliver(PHONE, "111111"))


def test_staging_reader_tolerates_damage(tmp_path: Path) -> None:
    path = tmp_path / "otp.json"
    path.write_text("not json")
    assert read_staging_codes(path, now=0) == {}
    path.write_text("[1, 2]")
    assert read_staging_codes(path, now=0) == {}


def test_admin_staging_code_lookup(tmp_path: Path) -> None:
    path = tmp_path / "otp.json"
    provider = StagingFileOtpProvider(str(path), [PHONE], ttl_seconds=3600)
    assert staging_code(str(path), PHONE) is None
    run(provider.deliver(PHONE, "424242"))
    assert staging_code(str(path), PHONE) == "424242"


def test_admin_rejects_bad_numbers() -> None:
    with pytest.raises(AdminError):
        validate_phone("12345")


class RecordingTransport:
    def __init__(self, error: Exception | None = None) -> None:
        self.messages: list[EmailMessage] = []
        self.error = error

    def send(self, message: EmailMessage) -> None:
        if self.error:
            raise self.error
        self.messages.append(message)


def test_smtp_provider_sends_the_code_to_the_destination() -> None:
    transport = RecordingTransport()
    provider = SmtpOtpProvider(transport, sender="noreply@example.com", timeout=1)
    run(provider.deliver("alice@example.com", "246810"))
    message = transport.messages[0]
    assert message["To"] == "alice@example.com" and message["From"] == "noreply@example.com"
    assert "246810" in message.get_content()


def test_smtp_failures_never_leak_server_text_or_the_code() -> None:
    transport = RecordingTransport(smtplib.SMTPAuthenticationError(535, b"bad password hunter2"))
    provider = SmtpOtpProvider(transport, sender="noreply@example.com", timeout=1)
    with pytest.raises(OtpDeliveryError) as info:
        run(provider.deliver("alice@example.com", "246810"))
    assert "hunter2" not in str(info.value) and "246810" not in str(info.value)


def test_smtp_network_error_is_a_delivery_error() -> None:
    provider = SmtpOtpProvider(
        RecordingTransport(ConnectionRefusedError()), sender="a@example.com", timeout=1
    )
    with pytest.raises(OtpDeliveryError):
        run(provider.deliver("alice@example.com", "246810"))


# ----------------------------------------------------- selection and settings


def test_unset_providers_are_disabled(make_settings: SettingsFactory) -> None:
    settings = make_settings()
    assert isinstance(build_sms_provider(settings), DisabledOtpProvider)
    assert isinstance(build_email_provider(settings), DisabledOtpProvider)


@pytest.mark.parametrize("provider", ["mock", "staging"])
def test_production_refuses_test_providers(make_settings: SettingsFactory, provider: str) -> None:
    with pytest.raises(ValidationError):
        make_settings(app_env="production", otp_provider=provider)


def test_mock_is_refused_outside_development_and_test(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(app_env="staging", otp_provider="mock")


def test_staging_provider_needs_file_and_allowlist(
    make_settings: SettingsFactory, tmp_path: Path
) -> None:
    with pytest.raises(ValidationError):
        make_settings(app_env="staging", otp_provider="staging")
    settings = make_settings(
        app_env="staging",
        otp_provider="staging",
        otp_staging_file=str(tmp_path / "otp.json"),
        otp_staging_allowlist=[PHONE],
    )
    assert isinstance(build_sms_provider(settings), StagingFileOtpProvider)


def test_smtp_needs_credentials_and_tls_when_deployed(make_settings: SettingsFactory) -> None:
    with pytest.raises(ValidationError):
        make_settings(otp_email_provider="smtp")
    base = {
        "otp_email_provider": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_from": "noreply@example.com",
        "smtp_username": "u",
        "smtp_password": "p",
    }
    assert isinstance(
        build_email_provider(make_settings(**base), RecordingTransport()), SmtpOtpProvider
    )
    with pytest.raises(ValidationError):
        make_settings(app_env="production", smtp_starttls=False, **base)


def test_smtp_password_is_not_printed(make_settings: SettingsFactory) -> None:
    settings = make_settings(
        otp_email_provider="smtp",
        smtp_host="h",
        smtp_from="a@example.com",
        smtp_username="u",
        smtp_password="s3cret-value",
    )
    assert "s3cret-value" not in repr(settings) and "s3cret-value" not in str(settings)


# --------------------------------------------------------------------- TOTP


def test_totp_rfc6238_vector() -> None:
    # RFC 6238 appendix B, SHA-1 secret "12345678901234567890", T=59s -> 94287082 (8 digits)
    secret = b"12345678901234567890"
    assert totp.code_at(secret, totp.current_step(59)) == "287082"


def test_totp_accepts_one_step_of_drift_only() -> None:
    secret = totp.new_secret()
    now = 1_700_000_000.0
    step = totp.current_step(now)
    assert totp.matching_step(secret, totp.code_at(secret, step - 1), now) == step - 1
    assert totp.matching_step(secret, totp.code_at(secret, step + 1), now) == step + 1
    assert totp.matching_step(secret, totp.code_at(secret, step + 3), now) is None
    assert totp.matching_step(secret, "abcdef", now) is None


def test_sealed_secret_is_bound_to_its_user() -> None:
    import uuid

    key, user, other = b"k" * 32, uuid.uuid4(), uuid.uuid4()
    secret = totp.new_secret()
    sealed = totp.seal(key, user, secret)
    assert secret not in sealed
    assert totp.unseal(key, user, sealed) == secret
    assert totp.unseal(key, other, sealed) is None
    assert totp.unseal(b"j" * 32, user, sealed) is None
