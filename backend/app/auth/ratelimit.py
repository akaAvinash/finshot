"""Fixed-window rate limits and resend cooldown, counted in Redis.

Subjects (phone, IP, context) are HMAC-hashed before they become key names, so
Redis never holds raw phone numbers or IPs. Redis errors propagate and the
request fails closed (HTTP 500)."""

from __future__ import annotations

from redis.asyncio import Redis

from app.auth.crypto import Keys, hmac_hex

# INCR + set the window on first hit; return {count, remaining ttl in ms}.
_HIT_SCRIPT = """
local c = redis.call('INCR', KEYS[1])
if c == 1 then redis.call('PEXPIRE', KEYS[1], ARGV[1]) end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then redis.call('PEXPIRE', KEYS[1], ARGV[1]); ttl = tonumber(ARGV[1]) end
return {c, ttl}
"""


# Give one event back (never below zero), for an attempt that turned out fine.
_RELEASE_SCRIPT = """
local c = tonumber(redis.call('GET', KEYS[1]) or '0')
if c > 0 then return redis.call('DECR', KEYS[1]) end
return 0
"""


# Reserve one slot only while under the limit (a rejected call changes nothing).
# The counter lives in a hash with the window's start time, so a later release
# can tell whether it still belongs to the same window.
_RESERVE_SCRIPT = """
local n = tonumber(redis.call('HGET', KEYS[1], 'n') or '0')
local w = redis.call('HGET', KEYS[1], 'w')
if not w then
  local t = redis.call('TIME')
  w = tostring(t[1] * 1000000 + t[2])
  redis.call('HSET', KEYS[1], 'n', 0, 'w', w)
  redis.call('PEXPIRE', KEYS[1], ARGV[1])
  n = 0
end
local ttl = redis.call('PTTL', KEYS[1])
if ttl < 0 then redis.call('PEXPIRE', KEYS[1], ARGV[1]); ttl = tonumber(ARGV[1]) end
if n >= tonumber(ARGV[2]) then return {0, ttl, w} end
redis.call('HINCRBY', KEYS[1], 'n', 1)
return {1, ttl, w}
"""

# Give a reservation back only if it is still the same window and above zero.
_RESERVE_RELEASE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'w') ~= ARGV[1] then return 0 end
local n = tonumber(redis.call('HGET', KEYS[1], 'n') or '0')
if n > 0 then return redis.call('HINCRBY', KEYS[1], 'n', -1) end
return 0
"""


def _ceil_seconds(ms: int) -> int:
    return max(1, -(-ms // 1000))


class RateLimiter:
    def __init__(self, redis: Redis, keys: Keys) -> None:
        self._redis = redis
        self._keys = keys

    def _key(self, kind: str, subject: str) -> str:
        return f"tradeo:rl:{kind}:{hmac_hex(self._keys.identifier, kind, subject)[:40]}"

    async def hit(self, kind: str, subject: str, limit: int, window_seconds: int) -> int | None:
        """Count one event. Returns seconds to wait if over the limit, else None."""
        raw = await self._redis.eval(
            _HIT_SCRIPT, 1, self._key(kind, subject), str(window_seconds * 1000)
        )
        count, ttl_ms = int(raw[0]), int(raw[1])
        return _ceil_seconds(ttl_ms) if count > limit else None

    def _rkey(self, kind: str, subject: str) -> str:
        return f"tradeo:rv:{kind}:{hmac_hex(self._keys.identifier, kind, subject)[:40]}"

    async def reserve(
        self, kind: str, subject: str, limit: int, window_seconds: int
    ) -> tuple[int | None, str]:
        """Take one slot if under `limit`; a rejected call does not count.

        Returns (seconds to wait or None, window token for `release_reservation`)."""
        raw = await self._redis.eval(
            _RESERVE_SCRIPT, 1, self._rkey(kind, subject), str(window_seconds * 1000), str(limit)
        )
        ok, ttl_ms, token = int(raw[0]), int(raw[1]), raw[2]
        token = token.decode() if isinstance(token, bytes) else str(token)
        return (None if ok else _ceil_seconds(ttl_ms)), token

    async def release_reservation(self, kind: str, subject: str, token: str) -> None:
        """Give back a reservation, only if its window is still the current one."""
        await self._redis.eval(_RESERVE_RELEASE_SCRIPT, 1, self._rkey(kind, subject), token)

    async def release(self, kind: str, subject: str) -> None:
        """Undo one earlier `hit` (for example after a successful login)."""
        await self._redis.eval(_RELEASE_SCRIPT, 1, self._key(kind, subject))

    async def exceeded(self, kind: str, subject: str, limit: int) -> int | None:
        """Without counting: seconds to wait if `limit` is already reached, else None."""
        key = self._key(kind, subject)
        raw = await self._redis.get(key)
        if raw is None or int(raw) < limit:
            return None
        ttl_ms = int(await self._redis.pttl(key))
        return _ceil_seconds(ttl_ms) if ttl_ms > 0 else 1

    async def cooldown(self, kind: str, subject: str, seconds: int) -> int | None:
        """Allow one event per `seconds`. Returns seconds to wait if too soon."""
        if seconds <= 0:
            return None
        key = self._key(kind, subject)
        if await self._redis.set(key, "1", nx=True, ex=seconds):
            return None
        ttl_ms = int(await self._redis.pttl(key))
        return _ceil_seconds(ttl_ms) if ttl_ms > 0 else 1
