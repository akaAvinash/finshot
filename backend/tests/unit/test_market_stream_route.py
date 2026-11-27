"""Pre-upgrade checks that need no database: disabled stream and Origin."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from app.main import create_app
from tests.conftest import SettingsFactory

URL = "/api/v1/market/stream?instrumentId=NSE:RELIANCE&timeframe=5m"


def test_disabled_stream_is_404(make_settings: SettingsFactory) -> None:
    with (
        TestClient(create_app(make_settings())) as client,
        pytest.raises(WebSocketDenialResponse) as denied,
        client.websocket_connect(URL, headers={"origin": "https://testserver"}),
    ):
        pass
    assert denied.value.status_code == 404
    assert denied.value.json()["code"] == "NOT_FOUND"


@pytest.mark.parametrize("origin", [None, "https://evil.example", "https://testserver:8443"])
def test_wrong_origin_is_403_before_any_session_lookup(
    make_settings: SettingsFactory, origin: str | None
) -> None:
    settings = make_settings(
        market_stream_enabled=True,
        market_stream_owner_user_id=uuid.uuid4(),
        market_stream_mock_tick_seconds=0.05,
    )
    headers = {"origin": origin} if origin else {}
    with (
        TestClient(create_app(settings)) as client,
        pytest.raises(WebSocketDenialResponse) as denied,
        client.websocket_connect(URL, headers=headers),
    ):
        pass
    assert denied.value.status_code == 403
    assert denied.value.json()["code"] == "ORIGIN_NOT_ALLOWED"


def test_session_store_down_is_503(make_settings: SettingsFactory) -> None:
    """The default test settings point at an unreachable database."""
    settings = make_settings(market_stream_enabled=True, market_stream_owner_user_id=uuid.uuid4())
    with (
        TestClient(create_app(settings)) as client,
        pytest.raises(WebSocketDenialResponse) as denied,
        client.websocket_connect(
            URL, headers={"origin": "https://testserver", "cookie": "__Host-tradeo_session=abc"}
        ),
    ):
        pass
    assert denied.value.status_code == 503


def test_only_the_owner_with_an_authenticator_is_eligible(make_settings: SettingsFactory) -> None:
    from datetime import UTC, datetime

    from app.api.routes.market_stream import _eligible
    from app.auth.service import SessionInfo

    owner = uuid.uuid4()
    settings = make_settings(market_stream_enabled=True, market_stream_owner_user_id=owner)
    now = datetime.now(UTC)

    def session(**kw: object) -> SessionInfo:
        values: dict[str, object] = {
            "session_id": uuid.uuid4(),
            "user_id": owner,
            "phone_e164": "+919876543210",
            "display_name": None,
            "user_created_at": now,
            "created_at": now,
            "last_seen_at": now,
            "expires_at": now,
            "device_label": None,
            "totp_enabled": True,
        }
        values.update(kw)
        return SessionInfo(**values)  # type: ignore[arg-type]

    assert _eligible(settings, session())
    assert not _eligible(settings, session(access="tester"))
    assert not _eligible(settings, session(totp_enabled=False))
    assert not _eligible(settings, session(user_id=uuid.uuid4()))
