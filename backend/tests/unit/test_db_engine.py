from __future__ import annotations

from app.db.session import create_engine
from tests.conftest import SettingsFactory


def test_engine_hides_bound_parameters(make_settings: SettingsFactory) -> None:
    engine = create_engine(make_settings())
    assert engine.sync_engine.hide_parameters is True
