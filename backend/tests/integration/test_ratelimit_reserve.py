"""Reservation semantics of RateLimiter (real Redis)."""

from __future__ import annotations

import asyncio
import os

import pytest
from redis.asyncio import Redis

from app.auth.crypto import Keys
from app.auth.ratelimit import RateLimiter


def _limiter(redis: Redis) -> RateLimiter:
    keys = Keys.__new__(Keys)
    object.__setattr__(keys, "identifier", b"k" * 32)
    return RateLimiter(redis, keys)


@pytest.fixture
async def redis() -> Redis:
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.skip("TEST_REDIS_URL unset")
    r = Redis.from_url(url)
    await r.flushdb()
    yield r
    await r.flushdb()
    await r.aclose()


async def test_rejected_reservations_do_not_count(redis: Redis) -> None:
    rl = _limiter(redis)
    tokens = []
    for _ in range(5):
        wait, tok = await rl.reserve("t", "p", 5, 60)
        assert wait is None
        tokens.append(tok)
    for _ in range(3):  # rejected: must not push the counter past the limit
        wait, _ = await rl.reserve("t", "p", 5, 60)
        assert wait is not None
    await rl.release_reservation("t", "p", tokens[0])
    wait, _ = await rl.reserve("t", "p", 5, 60)
    assert wait is None  # one slot was given back; rejects did not eat it
    wait, _ = await rl.reserve("t", "p", 5, 60)
    assert wait is not None


async def test_release_from_an_expired_window_is_ignored(redis: Redis) -> None:
    rl = _limiter(redis)
    _, old = await rl.reserve("t", "p", 2, 1)
    await asyncio.sleep(1.2)  # the window expires
    _, new = await rl.reserve("t", "p", 2, 60)
    assert new != old
    await rl.release_reservation("t", "p", old)  # must not touch the new window
    wait, _ = await rl.reserve("t", "p", 2, 60)
    assert wait is None
    wait, _ = await rl.reserve("t", "p", 2, 60)
    assert wait is not None  # still capped at two in the new window
