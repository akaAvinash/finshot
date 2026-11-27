"""Per-user paper engine: commands, workspace reads and the tick worker.

Every command locks the caller's paper account row (created on first use),
so commands and ticks on one account are serialised. The worker claims one
due running account at a time with FOR UPDATE SKIP LOCKED, replays one demo
session for it and commits, so several app processes can tick without
replaying the same session twice. Nothing here reaches a broker."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.alerts import producer as alerts
from app.auth.models import AuditEvent
from app.core.errors import ApiError
from app.db.session import begin_consistent_read
from app.market.demo import DemoMarketDataProvider
from app.paper import controls as tc
from app.paper import engine as rules
from app.paper.models import (
    PaperAccount,
    PaperEvent,
    PaperOrder,
    PaperReplay,
    PaperReplayFinish,
    PaperTrade,
    TradeControlChange,
    TradeControlsRow,
)
from app.paper.schemas import (
    RECENT_EVENTS,
    RECENT_ORDERS,
    RECENT_TRADES,
    AssignCommand,
    EngineCommand,
    HaltCommand,
    PaperAccountOut,
    PaperAgentOut,
    PaperEmptyOut,
    PaperEventOut,
    PaperOrderOut,
    PaperReadyOut,
    PaperReplayOut,
    PaperRiskOut,
    PaperSnapshotOut,
    PaperStrategyOut,
    PaperTradeOut,
)
from app.strategies.models import Strategy, StrategyVersion
from app.strategies.schemas import StrategyParameters

logger = structlog.get_logger(__name__)


def conflict(message: str) -> ApiError:
    return ApiError(409, "PAPER_CONFLICT", message)


def unavailable() -> ApiError:
    return ApiError(
        503, "PAPER_UNAVAILABLE", "Paper trading is temporarily unavailable. Try again shortly."
    )


class PaperService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        enabled: bool = True,
        tick_seconds: float = 3.0,
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._enabled = enabled
        self._tick = timedelta(seconds=tick_seconds)
        # Paper trading always replays the deterministic demo candles,
        # whatever MARKET_DATA_PROVIDER is set to.
        self._market = DemoMarketDataProvider()
        self._wake = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise unavailable()

    # ------------------------------------------------------------ demo inputs

    async def _symbols(self) -> dict[str, str]:
        """Instrument symbol -> demo instrument id."""
        return {i.symbol: i.id for i in await self._market.list_instruments()}

    async def _sessions(self, instrument_id: str) -> list[rules.Session]:
        candles = await self._market.get_candles(instrument_id, "1D")
        if candles is None:
            return []
        return [rules.Session(c.time, c.open, c.low, c.close, c.high) for c in candles.candles]

    # ----------------------------------------------------------------- reads

    async def workspace(self, user_id: uuid.UUID) -> PaperReadyOut | PaperEmptyOut:
        self._require_enabled()
        async with self._factory() as db:
            snapshot = await self._snapshot(db, user_id, allow_empty=True)
        return PaperEmptyOut() if snapshot is None else PaperReadyOut(data=snapshot)

    async def _snapshot(
        self, db: AsyncSession, user_id: uuid.UUID, *, allow_empty: bool
    ) -> PaperSnapshotOut | None:
        async with db.begin():
            await begin_consistent_read(db)
            account = await db.get(PaperAccount, user_id)
            active = (
                await db.scalars(
                    select(Strategy)
                    .where(Strategy.user_id == user_id, Strategy.status == "active")
                    .order_by(Strategy.seq)
                )
            ).all()
            latest = await _latest_versions(db, user_id, [s.id for s in active])
            orders: Sequence[PaperOrder] = []
            trades: Sequence[PaperTrade] = []
            if account is not None:
                orders = (
                    await db.scalars(
                        select(PaperOrder)
                        .where(PaperOrder.user_id == user_id, PaperOrder.replay == account.replay)
                        .order_by(PaperOrder.seq.desc())
                        .limit(RECENT_ORDERS)
                    )
                ).all()
                trades = (
                    await db.scalars(
                        select(PaperTrade)
                        .where(PaperTrade.user_id == user_id, PaperTrade.replay == account.replay)
                        .order_by(PaperTrade.seq.desc())
                        .limit(RECENT_TRADES)
                    )
                ).all()
            events = (
                await db.scalars(
                    select(PaperEvent)
                    .where(PaperEvent.user_id == user_id)
                    .order_by(PaperEvent.seq.desc())
                    .limit(RECENT_EVENTS)
                )
            ).all()
            assigned_active = False
            if account is not None and account.strategy_id is not None:
                assigned_active = any(s.id == account.strategy_id for s in active)
            revision, _updated, control_values = await _load_controls(db, user_id)
        # `replay` is 0 until the first assign: an account created only by
        # halt or another command has never assigned a strategy.
        never_assigned = account is None or account.replay == 0
        if never_assigned and not active and allow_empty:
            return None

        strategies: list[PaperStrategyOut] = []
        for s in active:
            if account is not None and s.id == account.strategy_id:
                number = account.version_number or 0
                raw = account.version_parameters or {}
            elif s.id in latest:
                number, raw = latest[s.id]
            else:
                continue
            params = StrategyParameters.model_validate(raw)
            strategies.append(
                PaperStrategyOut(
                    id=str(s.id), name=params.name, instrument=params.instrument, version=number
                )
            )

        if account is None:
            return PaperSnapshotOut(
                as_of=self._clock(),
                engine="idle",
                strategies=strategies,
                strategy_id=None,
                agent=PaperAgentOut(ready=False),
                risk=_risk_out(None, control_values, revision),
                account=PaperAccountOut(
                    capital_paise=rules.CAPITAL_PAISE,
                    cash_paise=rules.CAPITAL_PAISE,
                    equity_paise=rules.CAPITAL_PAISE,
                    position_quantity=0,
                    per_trade_risk_paise=_int(control_values["maxRiskPerTradePaise"]),
                ),
                replay=PaperReplayOut(
                    session_date=None, sessions_done=0, sessions_total=0, finished=False
                ),
                orders=[],
                trades=[],
                events=[_event_out(e) for e in reversed(events)],
            )

        equity = account.cash_paise
        session_date = None
        if account.instrument_id is not None and account.sessions_done > 0:
            sessions = await self._sessions(account.instrument_id)
            if len(sessions) >= account.sessions_done:
                last = sessions[account.sessions_done - 1]
                session_date = last.time.date()
                equity += account.position_quantity * rules.paise(last.close)
        return PaperSnapshotOut(
            as_of=self._clock(),
            engine=account.engine,
            strategies=strategies,
            strategy_id=None if account.strategy_id is None else str(account.strategy_id),
            agent=PaperAgentOut(ready=assigned_active and not account.finished),
            risk=_risk_out(account, control_values, revision),
            account=PaperAccountOut(
                capital_paise=account.capital_paise,
                cash_paise=account.cash_paise,
                equity_paise=equity,
                position_quantity=account.position_quantity,
                per_trade_risk_paise=_int(control_values["maxRiskPerTradePaise"]),
            ),
            replay=PaperReplayOut(
                session_date=session_date,
                sessions_done=account.sessions_done,
                sessions_total=account.sessions_total,
                finished=account.finished,
            ),
            orders=[_order_out(o) for o in orders],
            trades=[_trade_out(t) for t in trades],
            events=[_event_out(e) for e in reversed(events)],
        )

    # -------------------------------------------------------------- commands

    async def command(
        self, user_id: uuid.UUID, command: AssignCommand | EngineCommand | HaltCommand
    ) -> PaperSnapshotOut:
        self._require_enabled()
        symbols = await self._symbols()
        async with self._factory() as db:
            async with db.begin():
                now = self._clock()
                account = await self._locked_account(db, user_id, now)
                messages: list[str]
                if isinstance(command, AssignCommand):
                    messages = await self._assign(db, account, command.strategy_id, symbols, now)
                elif isinstance(command, HaltCommand):
                    messages = await self._halt(db, account, now)
                elif command.action == "start":
                    messages = await self._start(db, account)
                elif command.action == "pause":
                    if account.engine != "running":
                        raise conflict("The paper engine is not running.")
                    account.engine = "idle"
                    messages = ["Paper engine paused."]
                else:
                    if account.engine != "halted":
                        raise conflict("Only a halted paper engine can be reset.")
                    account.engine = "idle"
                    messages = ["Paper engine reset after a halt. It is idle."]
                if messages:
                    account.updated_at = now
                    for message in messages:
                        db.add(PaperEvent(user_id=user_id, message=message, created_at=now))
                    db.add(
                        AuditEvent(
                            user_id=user_id,
                            actor=f"user:{user_id}",
                            action=f"paper.{command.action}",
                            resource=f"paper:{user_id}",
                            metadata_redacted={"environment": "PAPER"},
                            created_at=now,
                        )
                    )
        if command.action == "start":
            self._wake.set()
        # Read the result in a new session, after the command committed.
        async with self._factory() as fresh:
            snapshot = await self._snapshot(fresh, user_id, allow_empty=False)
        if snapshot is None:  # pragma: no cover - the account row exists now
            raise unavailable()
        return snapshot

    # -------------------------------------------------------- trade controls

    def _controls_enabled(self) -> None:
        if not self._enabled:
            raise ApiError(
                503,
                "TRADE_CONTROLS_UNAVAILABLE",
                "Trade controls are temporarily unavailable. Try again shortly.",
            )

    async def trade_controls(self, user_id: uuid.UUID) -> tc.TradeControlsSettingsOut:
        self._controls_enabled()
        async with self._factory() as db:
            revision, updated_at, values = await _load_controls(db, user_id)
        return _settings_out(revision, updated_at, values)

    async def trade_controls_history(self, user_id: uuid.UUID) -> tc.TradeControlsHistoryOut:
        self._controls_enabled()
        async with self._factory() as db:
            rows = (
                await db.scalars(
                    select(TradeControlChange)
                    .where(TradeControlChange.user_id == user_id)
                    .order_by(TradeControlChange.revision.desc())
                    .limit(tc.HISTORY_LIMIT)
                )
            ).all()
        return tc.TradeControlsHistoryOut.model_validate(
            {
                "changes": [
                    {"revision": r.revision, "changed_at": r.changed_at, "fields": r.fields}
                    for r in rows
                ]
            }
        )

    async def update_trade_controls(
        self, user_id: uuid.UUID, body: tc.TradeControlsUpdateIn
    ) -> tc.TradeControlsSettingsOut:
        self._controls_enabled()
        new = body.controls.values()
        problems = tc.out_of_bounds(new)
        if problems:
            raise ApiError(
                400,
                "TRADE_CONTROLS_OUT_OF_BOUNDS",
                "Some limits are above what paper trading allows.",
                extra={"fieldErrors": problems},
            )
        async with self._factory() as db:
            async with db.begin():
                now = self._clock()
                account = await self._locked_account(db, user_id, now)
                if account.engine == "running":
                    raise ApiError(
                        409,
                        "TRADE_CONTROLS_ENGINE_RUNNING",
                        "Pause the paper engine before changing trade controls.",
                    )
                revision, updated_at, old = await _load_controls(db, user_id, lock=True)
                if body.expected_revision != revision:
                    raise ApiError(
                        409,
                        "TRADE_CONTROLS_REVISION_CONFLICT",
                        "These controls changed since you opened them. Reload to see the latest.",
                    )
                changes = tc.changed_fields(old, new)
                if not changes:
                    return _settings_out(revision, updated_at, old)
                columns = {tc.COLUMNS[name]: value for name, value in new.items()}
                if revision == 0:
                    db.add(TradeControlsRow(user_id=user_id, revision=1, updated_at=now, **columns))
                else:
                    await db.execute(
                        update(TradeControlsRow)
                        .where(TradeControlsRow.user_id == user_id)
                        .values(revision=revision + 1, updated_at=now, **columns)
                    )
                db.add(
                    TradeControlChange(
                        user_id=user_id, revision=revision + 1, changed_at=now, fields=changes
                    )
                )
                db.add(
                    AuditEvent(
                        user_id=user_id,
                        actor=f"user:{user_id}",
                        action="settings.trade_controls_updated",
                        resource=f"trade-controls:{user_id}",
                        metadata_redacted={
                            "environment": "PAPER",
                            "revision": revision + 1,
                            "fields": [c["field"] for c in changes],
                        },
                        created_at=now,
                    )
                )
                return _settings_out(revision + 1, now, new)

    async def _locked_account(
        self, db: AsyncSession, user_id: uuid.UUID, now: datetime
    ) -> PaperAccount:
        await db.execute(
            insert(PaperAccount)
            .values(
                user_id=user_id,
                engine="idle",
                replay=0,
                capital_paise=rules.CAPITAL_PAISE,
                cash_paise=rules.CAPITAL_PAISE,
                position_quantity=0,
                position_fees_paise=0,
                sessions_done=0,
                sessions_total=0,
                finished=False,
                session_pnl_paise=0,
                session_fills=0,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=[PaperAccount.user_id])
        )
        account = await db.scalar(
            select(PaperAccount)
            .where(PaperAccount.user_id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if account is None:  # pragma: no cover - inserted above
            raise unavailable()
        return account

    async def _assign(
        self,
        db: AsyncSession,
        account: PaperAccount,
        raw_id: str,
        symbols: dict[str, str],
        now: datetime,
    ) -> list[str]:
        if account.engine != "idle":
            raise conflict("Pause or reset the paper engine before assigning a strategy.")
        try:
            strategy_id = uuid.UUID(raw_id)
        except ValueError:
            raise conflict("Select one of your active strategies.") from None
        # FOR SHARE: a concurrent activation cannot add a version mid-assign.
        strategy = await db.scalar(
            select(Strategy)
            .where(Strategy.id == strategy_id, Strategy.user_id == account.user_id)
            .with_for_update(read=True)
        )
        if strategy is None or strategy.status != "active":
            raise conflict("Select one of your active strategies.")
        if account.strategy_id == strategy.id and not account.finished:
            return []  # Already assigned and its replay can continue: no change.
        latest = (await _latest_versions(db, account.user_id, [strategy.id])).get(strategy.id)
        if latest is None:
            raise conflict("Select one of your active strategies.")
        number, raw = latest
        params = StrategyParameters.model_validate(raw)
        instrument_id = symbols.get(params.instrument)
        sessions = [] if instrument_id is None else await self._sessions(instrument_id)
        if instrument_id is None or len(sessions) < rules.LOOKBACK:
            raise conflict("This strategy's instrument has no demo history to replay.")
        await _cancel_queued(db, account, now)
        account.strategy_id = strategy.id
        account.version_number = number
        account.version_parameters = raw
        account.instrument_id = instrument_id
        account.replay += 1
        db.add(
            PaperReplay(
                user_id=account.user_id,
                replay=account.replay,
                strategy_id=strategy.id,
                version_number=number,
                strategy_name=params.name,
                instrument_id=instrument_id,
                created_at=now,
            )
        )
        account.cash_paise = account.capital_paise
        _clear_position(account)
        account.sessions_done = 0
        account.sessions_total = len(sessions)
        account.finished = False
        account.session_pnl_paise = 0
        account.session_fills = 0
        account.session_peak_pnl_paise = 0
        account.session_loss_streak = 0
        account.last_tick_at = None
        return [f"Assigned {params.name} v{number} for a paper replay of {params.instrument}."]

    async def _start(self, db: AsyncSession, account: PaperAccount) -> list[str]:
        if account.engine != "idle":
            raise conflict("The paper engine can only start from idle.")
        if account.strategy_id is None:
            raise conflict("Assign a strategy before starting the paper engine.")
        if account.finished:
            raise conflict("This replay has finished. Assign a strategy to start a new one.")
        status = await db.scalar(select(Strategy.status).where(Strategy.id == account.strategy_id))
        if status != "active":
            raise conflict("The assigned strategy is no longer active.")
        account.engine = "running"
        return ["Paper engine started."]

    async def _halt(self, db: AsyncSession, account: PaperAccount, now: datetime) -> list[str]:
        if account.engine == "halted":
            raise conflict("The paper engine is already halted.")
        cancelled = await _cancel_queued(db, account, now)
        account.engine = "halted"
        message = f"Kill switch: engine halted and {cancelled} queued order(s) cancelled."
        await alerts.record(
            db,
            user_id=account.user_id,
            kind="PAPER_ENGINE_HALTED",
            dedupe_key=f"paper-halted:{uuid.uuid4()}",
            message=message,
            at=now,
        )
        return [message]

    # ---------------------------------------------------------------- worker

    async def tick_once(self) -> bool:
        """Replay one session for the next due running account. False when
        none is due."""
        symbols = await self._symbols()
        async with self._factory() as db, db.begin():
            now = self._clock()
            account = await db.scalar(
                select(PaperAccount)
                .where(
                    PaperAccount.engine == "running",
                    or_(
                        PaperAccount.last_tick_at.is_(None),
                        PaperAccount.last_tick_at <= now - self._tick,
                    ),
                )
                .order_by(PaperAccount.last_tick_at.asc().nulls_first())
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if account is None:
                return False
            account.last_tick_at = now
            account.updated_at = now
            status = await db.scalar(
                select(Strategy.status).where(Strategy.id == account.strategy_id)
            )
            if status != "active":
                account.engine = "idle"
                message = "The assigned strategy is no longer active. Engine paused."
                db.add(PaperEvent(user_id=account.user_id, message=message, created_at=now))
                await alerts.record(
                    db,
                    user_id=account.user_id,
                    kind="PAPER_STRATEGY_INACTIVE",
                    dedupe_key=f"paper-strategy-inactive:{account.replay}:{now.isoformat()}",
                    message=message,
                    at=now,
                )
                return True
            await self._replay_session(db, account, symbols, now)
        return True

    async def _replay_session(
        self, db: AsyncSession, account: PaperAccount, symbols: dict[str, str], now: datetime
    ) -> None:
        if account.instrument_id is None or account.version_parameters is None:
            account.engine = "idle"  # pragma: no cover - a running engine is always assigned
            return
        params = StrategyParameters.model_validate(account.version_parameters)
        sessions = await self._sessions(account.instrument_id)
        if account.sessions_done >= len(sessions):
            account.finished = True
            account.engine = "idle"
            await _record_finish(db, account, now)
            return
        queued_row = await db.scalar(
            select(PaperOrder)
            .where(
                PaperOrder.user_id == account.user_id,
                PaperOrder.replay == account.replay,
                PaperOrder.status == "queued",
            )
            .order_by(PaperOrder.seq)
            .limit(1)
        )
        state = rules.State(
            cash_paise=account.cash_paise,
            position_quantity=account.position_quantity,
            position_entry_paise=account.position_entry_paise,
            position_stop_paise=account.position_stop_paise,
            position_target_paise=account.position_target_paise,
            position_fees_paise=account.position_fees_paise,
            sessions_done=account.sessions_done,
        )
        _revision, _updated, control_values = await _load_controls(db, account.user_id)
        limits, size_bps, stop_loss_bps = tc.limits_for(
            control_values, params.position_size_bps, params.stop_loss_bps
        )
        queued = (
            None
            if queued_row is None
            else rules.QueuedOrder(
                "Buy" if queued_row.side == "Buy" else "Sell", queued_row.quantity
            )
        )
        out = rules.step(
            state,
            sessions,
            queued,
            size_bps=size_bps,
            stop_loss_bps=stop_loss_bps,
            symbol=params.instrument,
            limits=limits,
        )
        session_index = account.sessions_done
        if queued_row is not None and out.queued_outcome is not None:
            queued_row.status = out.queued_outcome
            if out.queued_outcome == "filled":
                queued_row.quantity = out.filled_quantity
            queued_row.updated_at = now
            if out.queued_outcome == "cancelled":
                await alerts.record(
                    db,
                    user_id=account.user_id,
                    kind="PAPER_ORDER_CANCELLED",
                    dedupe_key=f"paper-order-cancelled:{queued_row.id}",
                    message=(
                        f"{queued_row.side} order for {queued_row.quantity} "
                        f"{queued_row.instrument} cancelled: cash does not cover the open price."
                    ),
                    at=now,
                    link=("paper-order", str(queued_row.id)),
                )
        if out.risk_blocked:
            await alerts.record(
                db,
                user_id=account.user_id,
                kind="PAPER_RISK_LIMIT_REACHED",
                dedupe_key=f"paper-risk-limit:{account.replay}:{session_index}",
                message=(
                    f"A buy signal for {params.instrument} was blocked: a session risk limit"
                    " was reached."
                ),
                at=now,
            )
        for fill in out.fills:
            trade_id = uuid.uuid4()
            if fill.reason == "stop-loss":
                await alerts.record(
                    db,
                    user_id=account.user_id,
                    kind="PAPER_STOP_LOSS_EXIT",
                    dedupe_key=f"paper-stop-loss:{trade_id}",
                    message=(
                        f"Sold {fill.quantity} {params.instrument} at the stop-loss,"
                        f" {rules.rupees(fill.fill_paise)}."
                    ),
                    at=now,
                    link=("paper-trade", str(trade_id)),
                )
            db.add(
                PaperTrade(
                    id=trade_id,
                    user_id=account.user_id,
                    replay=account.replay,
                    instrument=params.instrument,
                    side=fill.side,
                    quantity=fill.quantity,
                    fill_paise=fill.fill_paise,
                    fees_paise=fill.fees_paise,
                    pnl_paise=fill.pnl_paise,
                    reason=fill.reason,
                    filled_at=fill.at,
                    created_at=now,
                )
            )
        if out.new_order is not None:
            db.add(
                PaperOrder(
                    user_id=account.user_id,
                    replay=account.replay,
                    instrument=params.instrument,
                    side=out.new_order.side,
                    quantity=out.new_order.quantity,
                    limit_paise=out.new_order.limit_paise,
                    status="queued",
                    created_at=now,
                    updated_at=now,
                )
            )
        for message in out.events:
            db.add(PaperEvent(user_id=account.user_id, message=message, created_at=now))
        account.cash_paise = state.cash_paise
        account.position_quantity = state.position_quantity
        account.position_entry_paise = state.position_entry_paise
        account.position_stop_paise = state.position_stop_paise
        account.position_target_paise = state.position_target_paise
        account.position_fees_paise = state.position_fees_paise
        account.session_pnl_paise = state.session_pnl_paise
        account.session_peak_pnl_paise = state.session_peak_pnl_paise
        account.session_loss_streak = state.session_loss_streak
        account.session_fills = state.session_fills
        account.sessions_done = state.sessions_done
        if out.finished:
            account.finished = True
            account.engine = "idle"
            await _cancel_queued(db, account, now)
            await _record_finish(db, account, now)

    async def run_worker(self, poll_seconds: float) -> None:
        """Tick running accounts until cancelled. `start` wakes the worker at
        once; otherwise it checks every `poll_seconds`."""
        while True:
            self._wake.clear()
            try:
                while await self.tick_once():
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The database may be briefly down; try again on the next poll.
                logger.warning("paper_worker_error", error_type=type(exc).__name__)
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=poll_seconds)
            except TimeoutError:
                pass


async def _latest_versions(
    db: AsyncSession, user_id: uuid.UUID, strategy_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, dict[str, Any]]]:
    if not strategy_ids:
        return {}
    newest = (
        select(StrategyVersion.strategy_id, func.max(StrategyVersion.number).label("number"))
        .where(StrategyVersion.user_id == user_id, StrategyVersion.strategy_id.in_(strategy_ids))
        .group_by(StrategyVersion.strategy_id)
        .subquery()
    )
    rows = await db.execute(
        select(
            StrategyVersion.strategy_id, StrategyVersion.number, StrategyVersion.parameters
        ).join(
            newest,
            and_(
                StrategyVersion.strategy_id == newest.c.strategy_id,
                StrategyVersion.number == newest.c.number,
            ),
        )
    )
    return {r.strategy_id: (r.number, r.parameters) for r in rows}


async def _cancel_queued(db: AsyncSession, account: PaperAccount, now: datetime) -> int:
    result = await db.execute(
        update(PaperOrder)
        .where(PaperOrder.user_id == account.user_id, PaperOrder.status == "queued")
        .values(status="cancelled", updated_at=now)
        .returning(PaperOrder.id)
    )
    return len(result.all())


async def _record_finish(db: AsyncSession, account: PaperAccount, now: datetime) -> None:
    await db.execute(
        insert(PaperReplayFinish)
        .values(user_id=account.user_id, replay=account.replay, finished_at=now)
        .on_conflict_do_nothing(
            index_elements=[PaperReplayFinish.user_id, PaperReplayFinish.replay]
        )
    )
    await alerts.record(
        db,
        user_id=account.user_id,
        kind="PAPER_REPLAY_FINISHED",
        dedupe_key=f"paper-replay-finished:{account.replay}",
        message=f"Paper replay {account.replay} replayed its last session. The engine is idle.",
        at=now,
        link=("paper-replay", str(account.replay)),
    )


def _clear_position(account: PaperAccount) -> None:
    account.position_quantity = 0
    account.position_entry_paise = None
    account.position_stop_paise = None
    account.position_target_paise = None
    account.position_fees_paise = 0


def _settings_out(
    revision: int, updated_at: datetime | None, values: dict[str, int | None]
) -> tc.TradeControlsSettingsOut:
    return tc.TradeControlsSettingsOut(
        revision=revision,
        updated_at=updated_at,
        controls=tc.TradeControlsOut.from_values(values),
        defaults=tc.TradeControlsOut.from_values(tc.DEFAULTS),
        bounds=tc.bounds_out(),
    )


def _int(value: int | None) -> int:
    if value is None:
        raise ValueError("a required Trade Control is null")
    return value


async def _load_controls(
    db: AsyncSession, user_id: uuid.UUID, *, lock: bool = False
) -> tuple[int, datetime | None, dict[str, int | None]]:
    """A user's revision, last save time and control values; the defaults at
    revision 0 when they never saved."""
    statement = select(TradeControlsRow).where(TradeControlsRow.user_id == user_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    row = await db.scalar(statement)
    if row is None:
        return 0, None, dict(tc.DEFAULTS)
    return row.revision, row.updated_at, {n: getattr(row, c) for n, c in tc.COLUMNS.items()}


def _risk_out(
    account: PaperAccount | None, control_values: dict[str, int | None], revision: int
) -> PaperRiskOut:
    """The caller's risk status under their effective limits."""
    limits, _size, _stop = tc.limits_for(control_values, rules.BASIS_POINTS, 1)
    state = rules.State(
        cash_paise=0,
        session_pnl_paise=0 if account is None else account.session_pnl_paise,
        session_peak_pnl_paise=0 if account is None else account.session_peak_pnl_paise,
        session_loss_streak=0 if account is None else account.session_loss_streak,
        session_fills=0 if account is None else account.session_fills,
    )
    reason: str | None = rules.blocked_reason(state, limits)
    if account is not None and account.engine == "halted":
        reason = "HALTED"
    return PaperRiskOut.model_validate(
        {
            "status": "approved" if reason is None else "blocked",
            "blocked_reason": reason,
            "daily_loss_paise": rules.session_loss(state),
            "loss_limit_paise": limits.loss_limit_paise,
            "trades_today": state.session_fills,
            "trade_limit": limits.trade_limit,
            "consecutive_losses": state.session_loss_streak,
            "controls_revision": revision,
        }
    )


def _order_out(order: PaperOrder) -> PaperOrderOut:
    return PaperOrderOut(
        id=str(order.id),
        instrument=order.instrument,
        side=order.side,
        quantity=order.quantity,
        limit_paise=order.limit_paise,
        status=order.status,
    )


def _trade_out(trade: PaperTrade) -> PaperTradeOut:
    return PaperTradeOut(
        id=str(trade.id),
        instrument=trade.instrument,
        side=trade.side,
        quantity=trade.quantity,
        fill_paise=trade.fill_paise,
        fees_paise=trade.fees_paise,
        pnl_paise=trade.pnl_paise,
        filled_at=trade.filled_at,
        reason=trade.reason,
    )


def _event_out(event: PaperEvent) -> PaperEventOut:
    return PaperEventOut(id=str(event.id), at=event.created_at, message=event.message)
