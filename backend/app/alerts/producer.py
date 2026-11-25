"""Recording alerts inside the transaction of the change they describe.

Producers (the paper engine, broker actions, sign-in) call `record` with the
session of their own transaction, so an alert exists exactly when its source
change committed. The insert uses ON CONFLICT DO NOTHING on the per-user
dedupe key, so recording the same occurrence twice is harmless."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.alerts.catalog import CATALOG, Kind, LinkKind
from app.alerts.models import Alert

MAX_MESSAGE = 500


async def record(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    kind: Kind,
    dedupe_key: str,
    message: str,
    at: datetime,
    link: tuple[LinkKind, str] | None = None,
) -> None:
    info = CATALOG[kind]
    await db.execute(
        insert(Alert)
        .values(
            user_id=user_id,
            dedupe_key=dedupe_key,
            kind=kind,
            source=info.source,
            severity=info.severity,
            environment=info.environment,
            title=info.title,
            message=message[:MAX_MESSAGE],
            link_kind=None if link is None else link[0],
            link_id=None if link is None else link[1],
            occurred_at=at,
            created_at=at,
        )
        .on_conflict_do_nothing(constraint="uq_alerts_dedupe")
    )
