"""Housekeeping for auth tables. Run on a schedule (cron, worker, or by hand):

python -m app.auth.maintenance
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import OtpChallenge
from app.auth.models import Session as SessionRow


async def purge_expired(
    db: AsyncSession,
    *,
    now: datetime | None = None,
    keep: timedelta = timedelta(hours=1),
    idle_ttl: timedelta = timedelta(minutes=30),
) -> dict[str, int]:
    """Delete OTP challenges and sessions that ended more than `keep` ago.

    OTP digests must not linger after they expire. Audit events are kept."""
    now = now or datetime.now(UTC)
    cutoff = now - keep
    otp = await db.execute(delete(OtpChallenge).where(OtpChallenge.expires_at < cutoff))
    sessions = await db.execute(
        delete(SessionRow).where(
            or_(
                SessionRow.expires_at < cutoff,
                SessionRow.revoked_at < cutoff,
                SessionRow.last_seen_at + idle_ttl < cutoff,  # ended by idle expiry
            )
        )
    )
    await db.commit()
    return {
        "otp_challenges": getattr(otp, "rowcount", 0) or 0,
        "sessions": getattr(sessions, "rowcount", 0) or 0,
    }


async def _main() -> None:
    from app.core.config import get_settings
    from app.db.session import create_engine, create_session_factory

    engine = create_engine(get_settings())
    try:
        async with create_session_factory(engine)() as db:
            print(
                await purge_expired(
                    db,
                    idle_ttl=timedelta(seconds=get_settings().session_idle_ttl_seconds),
                )
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
