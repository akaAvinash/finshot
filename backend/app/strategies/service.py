"""Per-user strategy commands.

Each command runs in one transaction. Commands on an existing strategy lock
its row; `create` takes a per-user advisory lock so the 100-strategy limit
holds under concurrency. Every successful command writes an audit event."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuditEvent
from app.core.errors import ApiError
from app.db.session import begin_consistent_read
from app.strategies.models import Strategy, StrategyVersion
from app.strategies.rules import risk_review
from app.strategies.schemas import (
    MAX_STRATEGIES,
    CreateCommand,
    SaveDraftCommand,
    StatusCommand,
    StrategyOut,
    StrategyParameters,
    StrategyRevisionOut,
    StrategySnapshotOut,
    StrategyVersionOut,
)


def parameters_hash(parameters: dict[str, Any]) -> str:
    canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def activation_blocker(backtest: str | None, risk_review: str | None) -> str | None:
    """Why a candidate revision cannot be activated, or None."""
    if backtest != "passed":
        return "A passing backtest for this revision is required."
    if risk_review != "approved":
        return "An approved risk review for this revision is required."
    return None


def not_found() -> ApiError:
    return ApiError(404, "STRATEGY_NOT_FOUND", "This strategy is not available.")


def conflict(message: str) -> ApiError:
    return ApiError(409, "STRATEGY_CONFLICT", message)


def unavailable() -> ApiError:
    return ApiError(
        503, "STRATEGY_UNAVAILABLE", "Strategies are temporarily unavailable. Try again shortly."
    )


class StrategyService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        enabled: bool = True,
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._enabled = enabled
        # Test seams: between the two snapshot reads, and after a command
        # commits but before its result is read.
        self._between_snapshot_reads: Callable[[], None] | None = None
        self._before_result_snapshot: Callable[[], None] | None = None

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise unavailable()

    async def snapshot(self, user_id: uuid.UUID) -> StrategySnapshotOut:
        self._require_enabled()
        async with self._factory() as db:
            return await self._snapshot(db, user_id, self._clock())

    async def command(
        self, user_id: uuid.UUID, command: CreateCommand | SaveDraftCommand | StatusCommand
    ) -> StrategySnapshotOut:
        self._require_enabled()
        async with self._factory() as db:
            now = self._clock()
            async with db.begin():
                if isinstance(command, CreateCommand):
                    strategy_id = await self._create(db, user_id, command.parameters, now)
                    action = "create"
                else:
                    strategy = await self._locked(db, user_id, command.id)
                    strategy_id = strategy.id
                    action = command.action
                    if isinstance(command, SaveDraftCommand):
                        _set_draft(strategy, command.parameters)
                    elif command.action == "activate":
                        await self._activate(db, user_id, strategy, now)
                    else:
                        if strategy.status != "active":
                            raise conflict("Only an active strategy can be paused.")
                        strategy.status = "paused"
                    strategy.updated_at = now
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor=f"user:{user_id}",
                        action=f"strategy.{action}",
                        resource=f"strategy:{strategy_id}",
                        metadata_redacted={"environment": "DEMO"},
                        created_at=now,
                    )
                )
        # Read the result in a new session: the command's session still holds
        # the objects it wrote, which would hide anything committed since.
        if self._before_result_snapshot is not None:
            self._before_result_snapshot()
        async with self._factory() as fresh:
            # asOf is when this result is read; audit rows keep the command time.
            return await self._snapshot(fresh, user_id, self._clock())

    async def _create(
        self, db: AsyncSession, user_id: uuid.UUID, parameters: StrategyParameters, now: datetime
    ) -> uuid.UUID:
        await db.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(f"strategies:{user_id}", 0)))
        )
        count = await db.scalar(
            select(func.count()).select_from(Strategy).where(Strategy.user_id == user_id)
        )
        if (count or 0) >= MAX_STRATEGIES:
            raise conflict(f"You can keep at most {MAX_STRATEGIES} strategies.")
        strategy = Strategy(user_id=user_id, status="draft", created_at=now, updated_at=now)
        _set_draft(strategy, parameters)
        db.add(strategy)
        await db.flush()
        return strategy.id

    async def _locked(self, db: AsyncSession, user_id: uuid.UUID, raw_id: str) -> Strategy:
        try:
            strategy_id = uuid.UUID(raw_id)
        except ValueError:
            raise not_found() from None
        strategy = await db.scalar(
            select(Strategy)
            .where(Strategy.id == strategy_id, Strategy.user_id == user_id)
            .with_for_update()
        )
        if strategy is None:
            raise not_found()
        return strategy

    async def _activate(
        self, db: AsyncSession, user_id: uuid.UUID, strategy: Strategy, now: datetime
    ) -> None:
        if strategy.status == "active":
            raise conflict("This strategy is already active.")
        latest = await db.scalar(
            select(func.max(StrategyVersion.number)).where(
                StrategyVersion.strategy_id == strategy.id
            )
        )
        if strategy.draft_parameters is None:
            # Reactivating a paused strategy: its latest version is already approved.
            if latest is None:
                raise conflict(activation_blocker(None, None) or "")
            strategy.status = "active"
            return
        blocker = activation_blocker(strategy.draft_backtest, strategy.draft_risk_review)
        if blocker:
            raise conflict(blocker)
        db.add(
            StrategyVersion(
                strategy_id=strategy.id,
                user_id=user_id,
                number=(latest or 0) + 1,
                parameters=strategy.draft_parameters,
                parameters_hash=parameters_hash(strategy.draft_parameters),
                activated_at=now,
            )
        )
        strategy.draft_parameters = None
        strategy.draft_backtest = None
        strategy.draft_risk_review = None
        strategy.status = "active"

    async def _snapshot(
        self, db: AsyncSession, user_id: uuid.UUID, now: datetime
    ) -> StrategySnapshotOut:
        # Both reads see one committed state, so a strategy never shows its
        # draft next to the version that a concurrent activation made from it.
        async with db.begin():
            await begin_consistent_read(db)
            strategies = (
                await db.scalars(
                    select(Strategy).where(Strategy.user_id == user_id).order_by(Strategy.seq)
                )
            ).all()
            if self._between_snapshot_reads is not None:
                self._between_snapshot_reads()
            versions = (
                await db.scalars(
                    select(StrategyVersion)
                    .where(StrategyVersion.user_id == user_id)
                    .order_by(StrategyVersion.strategy_id, StrategyVersion.number)
                )
            ).all()
        by_strategy: dict[uuid.UUID, list[StrategyVersionOut]] = {}
        for v in versions:
            by_strategy.setdefault(v.strategy_id, []).append(
                StrategyVersionOut(
                    number=v.number,
                    activated_at=v.activated_at,
                    parameters=StrategyParameters.model_validate(v.parameters),
                )
            )
        return StrategySnapshotOut(
            as_of=now,
            strategies=[
                StrategyOut(
                    id=str(s.id),
                    status=s.status,
                    draft=_draft_out(s),
                    versions=by_strategy.get(s.id, []),
                )
                for s in strategies
            ],
        )


def _set_draft(strategy: Strategy, parameters: StrategyParameters) -> None:
    strategy.draft_parameters = parameters.model_dump(mode="json")
    strategy.draft_backtest = "unavailable"
    strategy.draft_risk_review = risk_review(parameters)


def _draft_out(strategy: Strategy) -> StrategyRevisionOut | None:
    if strategy.draft_parameters is None:
        return None
    return StrategyRevisionOut(
        parameters=StrategyParameters.model_validate(strategy.draft_parameters),
        backtest=strategy.draft_backtest,
        risk_review=strategy.draft_risk_review,
    )
