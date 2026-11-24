from datetime import UTC, date, datetime

import pytest

from app.reports.service import csv_safe, inr, ist_date


@pytest.mark.parametrize(
    ("paise", "text"),
    [
        (0, "0.00"),
        (5, "0.05"),
        (-5, "-0.05"),
        (123450, "1234.50"),
        (-123450, "-1234.50"),
        (100_000_000, "1000000.00"),
    ],
)
def test_inr_is_exact(paise: int, text: str) -> None:
    assert inr(paise) == text


@pytest.mark.parametrize(
    ("value", "safe"),
    [
        ("=SUM(A1)", "'=SUM(A1)"),
        ("+cmd", "'+cmd"),
        ("-x", "'-x"),
        ("@x", "'@x"),
        ("-12.50", "-12.50"),
        ("+3", "+3"),
        ("SBIN", "SBIN"),
        ("", ""),
    ],
)
def test_csv_safe(value: str, safe: str) -> None:
    assert csv_safe(value) == safe


def test_ist_date_crosses_midnight() -> None:
    assert ist_date(datetime(2026, 1, 1, 18, 29, tzinfo=UTC)) == date(2026, 1, 1)
    assert ist_date(datetime(2026, 1, 1, 18, 30, tzinfo=UTC)) == date(2026, 1, 2)
