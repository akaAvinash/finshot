"""Per-user demo backtest runs and the in-process worker that completes them.

Queuing a run validates it, copies the strategy revision's parameters and
writes the run plus an audit event in one transaction. A per-user advisory
lock keeps the active-run limit under concurrency. The worker claims the
oldest queued run with FOR UPDATE SKIP LOCKED, so several app processes can
run workers without claiming the same run, and fails runs left `running` by
a worker that stopped."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import AuditEvent
from app.backtests.engine import BacktestInputError, Bar, Window, replay, window_bars
from app.backtests.models import BacktestRun
from app.backtests.schemas import (
    MAX_ACTIVE_RUNS,
    RECENT_RUNS,
    BacktestConfig,
    BacktestInstrumentOut,
    BacktestRunOut,
    BacktestStrategyOut,
    BacktestWorkspaceOut,
)
from app.core.errors import ApiError
from app.db.session import begin_consistent_read
from app.market.demo import DemoMarketDataProvider
from app.strategies.models import Strategy, StrategyVersion
from app.strategies.schemas import StrategyParameters

logger = structlog.get_logger(__name__)

INVALID_DATES = "Enter valid dates for the run window and holdout."
OUTSIDE_HISTORY = "Select a run window within the available demo history."
OUT_OF_ORDER = "The out-of-sample start must fall between the start and end dates."
UNKNOWN_INPUT = "Select an available demo strategy and instrument."
RUN_FAILED = "The demo worker could not complete this run. Start it again."
RUN_ABANDONED = "The run stopped before it finished. Start it again."


def invalid(message: str) -> ApiError:
    return ApiError(400, "INVALID_REQUEST", message)


def not_found() -> ApiError:
    return ApiError(404, "BACKTEST_NOT_FOUND", "This backtest is not available.")


def conflict() -> ApiError:
    return ApiError(
        409,
        "BACKTEST_CONFLICT",
        f"You can have at most {MAX_ACTIVE_RUNS} backtests queued or running."
        " Wait for one to finish.",
    )


def unavailable() -> ApiError:
    return ApiError(
        503, "BACKTEST_UNAVAILABLE", "Backtests are temporarily unavailable. Try again shortly."
    )


def revision_id(strategy_id: uuid.UUID, revision: int | str) -> str:
    return f"{strategy_id}:{revision}"


def parse_revision_id(value: str) -> tuple[uuid.UUID, int | str] | None:
    raw_strategy, sep, raw_revision = value.partition(":")
    if not sep:
        return None
    try:
        strategy_id = uuid.UUID(raw_strategy)
    except ValueError:
        return None
    if raw_revision == "draft":
        return strategy_id, "draft"
    if raw_revision.isascii() and raw_revision.isdigit() and not raw_revision.startswith("0"):
        return strategy_id, int(raw_revision)
    return None


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise invalid(INVALID_DATES) from None


def window_of(config: BacktestConfig) -> Window:
    return Window(
        start=_parse_date(config.start),
        end=_parse_date(config.end),
        out_of_sample_from=_parse_date(config.out_of_sample_from),
        capital_paise=config.capital_paise,
        fee_bps=config.fee_bps,
        slippage_bps=config.slippage_bps,
    )


class BacktestService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        enabled: bool = True,
        stale_after_seconds: float = 300.0,
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._enabled = enabled
        self._stale_after = timedelta(seconds=stale_after_seconds)
        # Backtests always replay the deterministic demo candles, whatever
        # MARKET_DATA_PROVIDER is set to.
        self._market = DemoMarketDataProvider()
        self._wake = asyncio.Event()
        # Test seam: after the worker marks a run running, before it replays.
        self._after_claim: Callable[[], None] | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise unavailable()

    # ------------------------------------------------------------ demo inputs

    async def _instruments(self) -> list[BacktestInstrumentOut]:
        listed = await self._market.list_instruments()
        return [BacktestInstrumentOut(id=i.id, symbol=i.symbol) for i in listed]

    async def _bars(self, instrument_id: str) -> list[Bar]:
        candles = await self._market.get_candles(instrument_id, "1D")
        if candles is None:
            return []
        return [Bar(c.time, c.open, c.close) for c in candles.candles]

    async def _history_range(self) -> tuple[date, date]:
        instruments = await self._instruments()
        bars = await self._bars(instruments[0].id)
        return bars[0].time.date(), bars[-1].time.date()

    # ----------------------------------------------------------------- reads

    async def workspace(self, user_id: uuid.UUID) -> BacktestWorkspaceOut:
        self._require_enabled()
        instruments = await self._instruments()
        start, end = await self._history_range()
        by_symbol = {i.symbol: i.id for i in instruments}
        async with self._factory() as db, db.begin():
            await begin_consistent_read(db)
            strategies = (
                await db.scalars(
                    select(Strategy).where(Strategy.user_id == user_id).order_by(Strategy.seq)
                )
            ).all()
            versions = (
                await db.scalars(
                    select(StrategyVersion)
                    .where(StrategyVersion.user_id == user_id)
                    .order_by(StrategyVersion.strategy_id, StrategyVersion.number)
                )
            ).all()
            runs = (
                await db.scalars(
                    select(BacktestRun)
                    .where(BacktestRun.user_id == user_id)
                    .order_by(BacktestRun.seq.desc())
                    .limit(RECENT_RUNS)
                )
            ).all()
        return BacktestWorkspaceOut(
            as_of=self._clock(),
            start=start.isoformat(),
            end=end.isoformat(),
            strategies=_revisions(strategies, versions, by_symbol),
            instruments=instruments,
            runs=[_run_out(r) for r in runs],
        )

    async def run(self, user_id: uuid.UUID, raw_id: str) -> BacktestRunOut:
        self._require_enabled()
        try:
            run_id = uuid.UUID(raw_id)
        except ValueError:
            raise not_found() from None
        async with self._factory() as db:
            run = await db.scalar(
                select(BacktestRun).where(BacktestRun.id == run_id, BacktestRun.user_id == user_id)
            )
        if run is None:
            raise not_found()
        return _run_out(run)

    # ----------------------------------------------------------------- queue

    async def start(self, user_id: uuid.UUID, config: BacktestConfig) -> BacktestRunOut:
        self._require_enabled()
        window = window_of(config)
        start, end = await self._history_range()
        if window.start < start or window.end > end:
            raise invalid(OUTSIDE_HISTORY)
        if not window.start < window.out_of_sample_from < window.end:
            raise invalid(OUT_OF_ORDER)
        instruments = await self._instruments()
        reference = parse_revision_id(config.strategy_id)
        if reference is None or config.instrument_id not in {i.id for i in instruments}:
            raise invalid(UNKNOWN_INPUT)
        try:
            window_bars(window, await self._bars(config.instrument_id))
        except BacktestInputError as exc:
            raise invalid(str(exc)) from None

        async with self._factory() as db:
            now = self._clock()
            async with db.begin():
                parameters = await self._revision_parameters(db, user_id, *reference)
                if parameters is None or parameters.instrument not in {
                    i.symbol for i in instruments
                }:
                    raise invalid(UNKNOWN_INPUT)
                await db.execute(
                    select(
                        func.pg_advisory_xact_lock(func.hashtextextended(f"backtests:{user_id}", 0))
                    )
                )
                active = await db.scalar(
                    select(func.count())
                    .select_from(BacktestRun)
                    .where(
                        BacktestRun.user_id == user_id,
                        BacktestRun.status.in_(("queued", "running")),
                    )
                )
                if (active or 0) >= MAX_ACTIVE_RUNS:
                    raise conflict()
                run = BacktestRun(
                    user_id=user_id,
                    strategy_id=reference[0],
                    config=config.model_dump(mode="json", by_alias=True),
                    parameters=parameters.model_dump(mode="json"),
                    status="queued",
                    queued_at=now,
                    updated_at=now,
                )
                db.add(run)
                await db.flush()
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor=f"user:{user_id}",
                        action="backtest.queue",
                        resource=f"backtest:{run.id}",
                        metadata_redacted={"environment": "DEMO"},
                        created_at=now,
                    )
                )
        self._wake.set()
        return _run_out(run)

    async def _revision_parameters(
        self, db: AsyncSession, user_id: uuid.UUID, strategy_id: uuid.UUID, revision: int | str
    ) -> StrategyParameters | None:
        raw: dict[str, Any] | None
        if revision == "draft":
            raw = await db.scalar(
                select(Strategy.draft_parameters).where(
                    Strategy.id == strategy_id, Strategy.user_id == user_id
                )
            )
        else:
            raw = await db.scalar(
                select(StrategyVersion.parameters).where(
                    StrategyVersion.strategy_id == strategy_id,
                    StrategyVersion.user_id == user_id,
                    StrategyVersion.number == revision,
                )
            )
        return None if raw is None else StrategyParameters.model_validate(raw)

    # ---------------------------------------------------------------- worker

    async def process_next(self) -> bool:
        """Claim and finish the oldest queued run. False when none is queued."""
        async with self._factory() as db:
            async with db.begin():
                run = await db.scalar(
                    select(BacktestRun)
                    .where(BacktestRun.status == "queued")
                    .order_by(BacktestRun.seq)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
                if run is None:
                    return False
                now = self._clock()
                run.status = "running"
                run.started_at = now
                run.updated_at = now
                run_id, config, parameters = run.id, run.config, run.parameters
            if self._after_claim is not None:
                self._after_claim()
            result: dict[str, Any] | None = None
            try:
                result = await self._replay(config, parameters)
            except Exception as exc:
                logger.warning("backtest_failed", run_id=str(run_id), error_type=type(exc).__name__)
            async with db.begin():
                # A run failed as abandoned in the meantime keeps that outcome.
                await db.execute(
                    update(BacktestRun)
                    .where(BacktestRun.id == run_id, BacktestRun.status == "running")
                    .values(
                        status="failed" if result is None else "completed",
                        result=result,
                        message=RUN_FAILED if result is None else None,
                        updated_at=self._clock(),
                    )
                )
        return True

    async def _replay(self, config: dict[str, Any], parameters: dict[str, Any]) -> dict[str, Any]:
        accepted = BacktestConfig.model_validate(config)
        position_size = StrategyParameters.model_validate(parameters).position_size_bps
        bars = await self._bars(accepted.instrument_id)
        return replay(window_of(accepted), bars, position_size)

    async def fail_abandoned(self) -> int:
        """Fail runs left `running` longer than the stale limit."""
        now = self._clock()
        async with self._factory() as db, db.begin():
            result = await db.execute(
                update(BacktestRun)
                .where(
                    BacktestRun.status == "running",
                    BacktestRun.started_at < now - self._stale_after,
                )
                .values(status="failed", message=RUN_ABANDONED, updated_at=now)
                .returning(BacktestRun.id)
            )
            return len(result.all())

    async def run_worker(self, poll_seconds: float) -> None:
        """Process runs until cancelled. A new run wakes the worker at once;
        otherwise it checks every `poll_seconds`."""
        while True:
            self._wake.clear()
            try:
                await self.fail_abandoned()
                while await self.process_next():
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The database may be briefly down; try again on the next tick.
                logger.warning("backtest_worker_error", error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass


def _revisions(
    strategies: Sequence[Strategy],
    versions: Sequence[StrategyVersion],
    by_symbol: dict[str, str],
) -> list[BacktestStrategyOut]:
    by_strategy: dict[uuid.UUID, list[StrategyVersion]] = {}
    for v in versions:
        by_strategy.setdefault(v.strategy_id, []).append(v)
    out: list[BacktestStrategyOut] = []
    for s in strategies:
        revisions: list[tuple[int | str, dict[str, Any]]] = [
            (v.number, v.parameters) for v in by_strategy.get(s.id, [])
        ]
        if s.draft_parameters is not None:
            revisions.append(("draft", s.draft_parameters))
        for revision, raw in revisions:
            parameters = StrategyParameters.model_validate(raw)
            instrument_id = by_symbol.get(parameters.instrument)
            if instrument_id is None:
                continue
            out.append(
                BacktestStrategyOut(
                    id=revision_id(s.id, revision),
                    name=parameters.name,
                    revision=revision if isinstance(revision, int) else "draft",
                    instrument_id=instrument_id,
                    position_size_bps=parameters.position_size_bps,
                )
            )
    return out


def _run_out(run: BacktestRun) -> BacktestRunOut:
    return BacktestRunOut(
        id=str(run.id),
        as_of=run.updated_at,
        queued_at=run.queued_at,
        config=BacktestConfig.model_validate(run.config),
        status=run.status,
        result=run.result,
        message=run.message,
    )
