"""Redis client factory. The client connects lazily on first command."""

from __future__ import annotations

from redis.asyncio import Redis

from app.core.config import Settings


def create_redis(settings: Settings) -> Redis:
    return Redis.from_url(
        str(settings.redis_url),
        socket_timeout=settings.redis_socket_timeout_seconds,
        socket_connect_timeout=settings.redis_socket_timeout_seconds,
        health_check_interval=30,
        decode_responses=True,
    )


async def ping_redis(client: Redis) -> None:
    if not await client.ping():
        raise ConnectionError("redis ping returned false")
