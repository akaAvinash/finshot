"""Advisory agents: the evaluation worker and the read-only endpoints.

The worker claims one user whose paper account changed since the agents last
evaluated it (FOR UPDATE SKIP LOCKED on the user's agent_runs row, so several
app processes never evaluate one user at once), reads that user's paper data,
runs app.agents.rules and inserts the resulting events with ON CONFLICT DO
NOTHING on their dedupe key. It only reads paper tables: it never locks or
writes them, sends a paper command or changes a risk limit, and the paper
engine never reads agent tables. No language model or network call is made.

Reads use one REPEATABLE READ, READ ONLY transaction per response. Event
links are returned only after checking, in that transaction, that the paper
record exists and belongs to the caller."""

from __future__ import annotations

import asyncio
import base64
import binascii
import re
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

import structlog
from sqlalchemy import String, and_, case, cast, func, literal, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents import rules
from app.agents.models import AgentEvent, AgentRun, AgentWorker
from app.agents.schemas import (
    AGENT_IDS,
    AgentEventOut,
    AgentEventPageOut,
    AgentHealthOut,
    AgentHealthReportOut,
    AgentId,
    AgentLinkOut,
    AgentRosterOut,
    HealthReason,
)
from app.core.errors import ApiError
from app.db.session import begin_consistent_read
from app.market.demo import DemoMarketDataProvider
from app.paper import engine as paper
from app.paper.models import (
    PaperAccount,
    PaperOrder,
    PaperReplay,
    PaperReplayFinish,
    PaperTrade,
)
from app.retention.service import purged_floor
from app.strategies.models import StrategyVersion

logger = structlog.get_logger(__name__)

MAX_SEQ = 2**63 - 1  # PostgreSQL bigint
_CURSOR = re.compile(r"v1:(\*|[a-z-]{1,32}):([1-9][0-9]{0,18})")


def unavailable() -> ApiError:
    return ApiError(
        503, "AGENTS_UNAVAILABLE", "Agents are temporarily unavailable. Try again shortly."
    )


def invalid_cursor() -> ApiError:
    return ApiError(
        400, "INVALID_REQUEST", "The page cursor is invalid. Start from the first page."
    )


def encode_cursor(agent_id: AgentId | None, seq: int) -> str:
    raw = f"v1:{agent_id or '*'}:{seq}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, agent_id: AgentId | None) -> int:
    """The sequence a cursor continues before. Raises 400 when it is malformed
    or was issued for another `agentId` filter."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        raise invalid_cursor() from None
    match = _CURSOR.fullmatch(raw)
    if (
        match is None
        or match.group(1) != (agent_id or "*")
        or encode_cursor(agent_id, int(match.group(2))) != cursor
    ):
        raise invalid_cursor()
    seq = int(match.group(2))
    if seq > MAX_SEQ:
        raise invalid_cursor()
    return seq


class AgentService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        clock: Callable[[], datetime],
        enabled: bool = True,
        stale_after_seconds: int = 30,
    ) -> None:
        self._factory = session_factory
        self._clock = clock
        self._enabled = enabled
        self._stale = timedelta(seconds=stale_after_seconds)
        self._stale_seconds = stale_after_seconds
        # Paper replays use the deterministic demo candles, so the scanner does too.
        self._market = DemoMarketDataProvider()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise unavailable()

    # ----------------------------------------------------------------- reads

    def roster(self) -> AgentRosterOut:
        self._require_enabled()
        return AgentRosterOut(agents=list(rules.ROSTER))

    async def health(self, user_id: uuid.UUID) -> AgentHealthReportOut:
        self._require_enabled()
        async with self._factory() as db, db.begin():
            await begin_consistent_read(db)
            now = self._clock()
            account = await db.get(PaperAccount, user_id)
            run = await db.get(AgentRun, user_id)
            worker = await db.get(AgentWorker, 1)
        pass_ended_at = None if worker is None else worker.pass_ended_at
        status, reason = self._agent_status(account, run, pass_ended_at, now)
        last_run = None if run is None else run.last_run_at
        data_as_of = None if run is None or run.last_run_at is None else run.data_as_of
        agents = [
            AgentHealthOut(
                agent_id=agent_id,
                status=status,
                reason_code=reason,
                last_run_at=last_run if reason != "NO_PAPER_ACTIVITY" else None,
                data_as_of=data_as_of if reason != "NO_PAPER_ACTIVITY" else None,
                stale_after_seconds=self._stale_seconds,
            )
            for agent_id in AGENT_IDS
        ]
        statuses = {a.status for a in agents}
        overall = (
            "ok"
            if statuses == {"ok"}
            else "unavailable"
            if statuses == {"unavailable"}
            else "degraded"
        )
        return AgentHealthReportOut(as_of=now, status=overall, agents=agents)

    def _agent_status(
        self,
        account: PaperAccount | None,
        run: AgentRun | None,
        pass_ended_at: datetime | None,
        now: datetime,
    ) -> tuple[Literal["ok", "stale", "unavailable"], HealthReason | None]:
        """The contract's ordered health rules; the first that applies wins."""
        if account is None or account.replay == 0:
            return "unavailable", "NO_PAPER_ACTIVITY"
        evaluated = run is not None and run.last_run_at is not None
        pending = not evaluated or run is None or run.data_as_of != account.updated_at
        worker_quiet = pass_ended_at is None or now - pass_ended_at > self._stale
        if pending and (now - account.updated_at > self._stale or worker_quiet):
            return "stale", "DATA_STALE"
        if not evaluated:
            return "unavailable", "NOT_YET_EVALUATED"
        return "ok", None

    async def events(
        self, user_id: uuid.UUID, agent_id: AgentId | None, cursor: str | None, limit: int
    ) -> AgentEventPageOut:
        self._require_enabled()
        before = None if cursor is None else decode_cursor(cursor, agent_id)
        query = select(AgentEvent).where(AgentEvent.user_id == user_id)
        if agent_id is not None:
            query = query.where(AgentEvent.agent_id == agent_id)
        if before is not None:
            query = query.where(AgentEvent.seq < before)
        query = query.order_by(AgentEvent.seq.desc()).limit(limit + 1)
        async with self._factory() as db, db.begin():
            await begin_consistent_read(db)
            rows = list((await db.scalars(query)).all())
            page = rows[:limit]
            verified = await _verified_links(db, user_id, page)
        items = [
            AgentEventOut(
                id=str(row.id),
                agent_id=row.agent_id,
                at=row.created_at,
                data_as_of=row.data_as_of,
                severity=row.severity,
                reason_code=row.reason_code,
                message=row.message,
                recommendation=row.recommendation,
                link=(
                    AgentLinkOut(kind=row.link_kind, id=row.link_id)
                    if row.link_kind is not None
                    and row.link_id is not None
                    and (row.link_kind, row.link_id) in verified
                    else None
                ),
            )
            for row in page
        ]
        next_cursor = encode_cursor(agent_id, page[-1].seq) if len(rows) > limit else None
        return AgentEventPageOut(items=items, next_cursor=next_cursor)

    # ---------------------------------------------------------------- worker

    async def discover(self) -> None:
        """Track accounts that have a replay but no agent run yet."""
        async with self._factory() as db, db.begin():
            await _discover(db)

    async def run_once(self, *, discover: bool = True) -> bool:
        """Evaluate one user whose paper data changed since the agents last
        did. False when every user is up to date. The worker discovers once
        per poll and passes `discover=False`."""
        async with self._factory() as db, db.begin():
            now = self._clock()
            if discover:
                await _discover(db)
            pending = (
                select(AgentRun)
                .join(PaperAccount, PaperAccount.user_id == AgentRun.user_id)
                .where(
                    PaperAccount.replay >= 1,
                    or_(
                        AgentRun.last_run_at.is_(None),
                        AgentRun.data_as_of.is_distinct_from(PaperAccount.updated_at),
                    ),
                )
            )
            run = await db.scalar(
                pending.order_by(PaperAccount.updated_at)
                .limit(1)
                .with_for_update(of=AgentRun, skip_locked=True)
            )
            if run is None:
                # SKIP LOCKED hides users another worker holds; the pass has
                # ended only when no user is pending at all.
                if await db.scalar(select(pending.exists())):
                    return False
                await db.execute(
                    insert(AgentWorker)
                    .values(id=1, pass_ended_at=now)
                    .on_conflict_do_update(
                        index_elements=[AgentWorker.id],
                        set_={"pass_ended_at": func.greatest(AgentWorker.pass_ended_at, now)},
                    )
                )
                return False
            observation = await self._observe(db, run)
            if observation is None:  # pragma: no cover - the account cannot vanish here
                return True
            result = rules.evaluate(observation, rules.Memory.load(run.state))
            if result.events:
                await db.execute(
                    insert(AgentEvent)
                    .values(
                        [
                            {
                                "user_id": run.user_id,
                                "agent_id": e.agent_id,
                                "dedupe_key": e.dedupe_key,
                                "reason_code": e.reason_code,
                                "severity": e.severity,
                                "message": e.message,
                                "recommendation": e.recommendation,
                                "link_kind": e.link_kind,
                                "link_id": e.link_id,
                                "data_as_of": e.data_as_of,
                                "created_at": now,
                            }
                            for e in result.events
                        ]
                    )
                    .on_conflict_do_nothing(constraint="uq_agent_events_dedupe")
                )
            await db.execute(
                update(AgentRun)
                .where(AgentRun.user_id == run.user_id)
                .values(
                    last_run_at=now,
                    data_as_of=observation.changed_at,
                    state=result.memory.dump(),
                )
            )
        return True

    async def _observe(self, db: AsyncSession, run: AgentRun) -> rules.Observation | None:
        user_id = run.user_id
        memory = rules.Memory.load(run.state)
        gross = PaperTrade.fill_paise * PaperTrade.quantity
        replay_trades = and_(
            PaperTrade.user_id == PaperAccount.user_id, PaperTrade.replay == PaperAccount.replay
        )
        ledger_cash = (
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (PaperTrade.side == "Sell", gross - PaperTrade.fees_paise),
                            else_=-(gross + PaperTrade.fees_paise),
                        )
                    ),
                    0,
                )
            )
            .where(replay_trades)
            .scalar_subquery()
        )
        ledger_quantity = (
            select(
                func.coalesce(
                    func.sum(
                        case(
                            (PaperTrade.side == "Sell", -PaperTrade.quantity),
                            else_=PaperTrade.quantity,
                        )
                    ),
                    0,
                )
            )
            .where(replay_trades)
            .scalar_subquery()
        )
        # One statement, so the account and its ledger come from one snapshot.
        row = (
            await db.execute(
                select(PaperAccount, ledger_cash, ledger_quantity).where(
                    PaperAccount.user_id == user_id
                )
            )
        ).one_or_none()
        if row is None:
            return None
        account: PaperAccount = row[0]
        reconciled = (
            account.capital_paise + int(row[1]) == account.cash_paise
            and int(row[2]) == account.position_quantity
        )
        trades = (
            await db.scalars(
                select(PaperTrade)
                .where(PaperTrade.user_id == user_id, PaperTrade.seq > memory.trade_seq)
                .order_by(PaperTrade.seq)
            )
        ).all()
        reported = select(AgentEvent.id).where(
            AgentEvent.user_id == user_id,
            AgentEvent.agent_id == "execution-monitor",
            AgentEvent.dedupe_key == func.concat("cancel:", cast(PaperOrder.id, String)),
        )
        cancelled = (
            await db.scalars(
                select(PaperOrder)
                .where(
                    PaperOrder.user_id == user_id,
                    PaperOrder.status == "cancelled",
                    # Older than the retention purge: its event may be gone.
                    PaperOrder.updated_at > purged_floor(PaperOrder.user_id),
                    ~reported.exists(),
                )
                .order_by(PaperOrder.seq)
            )
        ).all()
        summarised = select(AgentEvent.id).where(
            AgentEvent.user_id == user_id,
            AgentEvent.agent_id == "strategy-analyst",
            AgentEvent.dedupe_key == func.concat("replay:", cast(PaperReplayFinish.replay, String)),
        )
        replay_fills = and_(
            PaperTrade.user_id == PaperReplayFinish.user_id,
            PaperTrade.replay == PaperReplayFinish.replay,
        )
        finished = (
            await db.execute(
                select(
                    PaperReplayFinish.replay,
                    PaperReplayFinish.finished_at,
                    select(func.count()).where(replay_fills).scalar_subquery(),
                    select(func.count())
                    .where(replay_fills, PaperTrade.side == "Sell", PaperTrade.pnl_paise > 0)
                    .scalar_subquery(),
                    select(func.coalesce(func.sum(PaperTrade.pnl_paise), 0))
                    .where(replay_fills)
                    .scalar_subquery(),
                    select(func.max(PaperTrade.filled_at)).where(replay_fills).scalar_subquery(),
                )
                .where(
                    PaperReplayFinish.user_id == user_id,
                    PaperReplayFinish.finished_at > purged_floor(PaperReplayFinish.user_id),
                    ~summarised.exists(),
                )
                .order_by(PaperReplayFinish.replay)
            )
        ).all()
        summaries = [
            rules.ReplaySummary(
                replay=int(r[0]),
                finished_at=r[1],
                fills=int(r[2]),
                winning_sells=int(r[3]),
                realised_paise=int(r[4]),
                last_fill_at=r[5],
            )
            for r in finished
        ]
        closes: list[rules.Close] = []
        if account.instrument_id is not None:
            candles = await self._market.get_candles(account.instrument_id, "1D")
            if candles is not None:
                closes = [rules.Close(c.time, paper.paise(c.close)) for c in candles.candles]
        backlog: list[rules.ReplayScan] = []
        unscanned = (
            await db.execute(
                select(PaperReplay.replay, PaperReplay.instrument_id, StrategyVersion.parameters)
                .join(
                    PaperReplayFinish,
                    and_(
                        PaperReplayFinish.user_id == PaperReplay.user_id,
                        PaperReplayFinish.replay == PaperReplay.replay,
                    ),
                )
                .outerjoin(
                    StrategyVersion,
                    and_(
                        StrategyVersion.strategy_id == PaperReplay.strategy_id,
                        StrategyVersion.number == PaperReplay.version_number,
                    ),
                )
                .where(
                    PaperReplay.user_id == user_id,
                    PaperReplay.replay >= memory.scan_replay,
                    PaperReplay.replay < account.replay,
                )
                .order_by(PaperReplay.replay)
            )
        ).all()
        for replay_no, instrument_id, parameters in unscanned:
            history = await self._market.get_candles(instrument_id, "1D")
            backlog.append(
                rules.ReplayScan(
                    replay=int(replay_no),
                    symbol=str((parameters or {}).get("instrument") or instrument_id),
                    closes=[]
                    if history is None
                    else [rules.Close(c.time, paper.paise(c.close)) for c in history.candles],
                )
            )
        symbol = None
        if account.version_parameters is not None:
            symbol = str(account.version_parameters.get("instrument") or account.instrument_id)
        return rules.Observation(
            replay=account.replay,
            engine=account.engine,
            changed_at=account.updated_at,
            symbol=symbol,
            sessions_done=account.sessions_done,
            closes=closes,
            trades=[
                rules.Trade(
                    id=str(t.id),
                    seq=t.seq,
                    replay=t.replay,
                    instrument=t.instrument,
                    side=t.side,
                    quantity=t.quantity,
                    fill_paise=t.fill_paise,
                    pnl_paise=t.pnl_paise,
                    reason=t.reason,
                    filled_at=t.filled_at,
                )
                for t in trades
            ],
            cancelled=[
                rules.CancelledOrder(
                    id=str(o.id),
                    replay=o.replay,
                    instrument=o.instrument,
                    side=o.side,
                    quantity=o.quantity,
                    cancelled_at=o.updated_at,
                )
                for o in cancelled
            ],
            reconciled=reconciled if account.replay >= 1 else None,
            summaries=summaries,
            backlog=backlog,
        )

    async def run_worker(self, poll_seconds: float) -> None:
        """Evaluate changed users until cancelled, checking every `poll_seconds`."""
        while True:
            try:
                await self.discover()
                while await self.run_once(discover=False):
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The database may be briefly down; try again on the next poll.
                logger.warning("agent_worker_error", error_type=type(exc).__name__)
            await asyncio.sleep(poll_seconds)


async def _discover(db: AsyncSession) -> None:
    await db.execute(
        insert(AgentRun)
        .from_select(
            ["user_id", "state"],
            # Only accounts not yet tracked, so a pass does not
            # resubmit every account on every call.
            select(PaperAccount.user_id, literal({}, AgentRun.state.type)).where(
                PaperAccount.replay >= 1,
                ~select(AgentRun.user_id).where(AgentRun.user_id == PaperAccount.user_id).exists(),
            ),
        )
        .on_conflict_do_nothing(index_elements=[AgentRun.user_id])
    )


async def _verified_links(
    db: AsyncSession, user_id: uuid.UUID, rows: list[AgentEvent]
) -> set[tuple[str, str]]:
    """(kind, id) pairs among `rows`' links whose record exists and is the user's."""
    wanted: dict[str, set[str]] = {
        "paper-trade": set(),
        "paper-order": set(),
        "paper-replay": set(),
    }
    for row in rows:
        if row.link_kind in wanted and row.link_id is not None:
            wanted[row.link_kind].add(row.link_id)
    found: set[tuple[str, str]] = set()
    for kind, model in (("paper-trade", PaperTrade), ("paper-order", PaperOrder)):
        ids = [i for i in (_uuid(v) for v in wanted[kind]) if i is not None]
        if ids:
            matched = await db.scalars(
                select(model.id).where(model.user_id == user_id, model.id.in_(ids))
            )
            found |= {(kind, str(i)) for i in matched}
    replays = [int(v) for v in wanted["paper-replay"] if v.isdigit() and len(v) <= 9]
    if replays:
        matched_replays = await db.scalars(
            select(PaperReplay.replay).where(
                PaperReplay.user_id == user_id, PaperReplay.replay.in_(replays)
            )
        )
        found |= {("paper-replay", str(r)) for r in matched_replays}
    return found


def _uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None
