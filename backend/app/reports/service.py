"""Paper P&L report and CSV export (contract 0.8.0, getPaperReport and
exportPaperTrades).

Everything is derived from the caller's paper ledger: paper_trades for fills,
paper_replays for which strategy version made them, and paper_accounts for
the current replay's open position and the reconciliation. One REPEATABLE READ
transaction backs each response, so all its parts agree."""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import Date, and_, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.elements import ColumnElement

from app.core.errors import ApiError
from app.db.session import begin_consistent_read
from app.market.demo import DemoMarketDataProvider
from app.paper import engine as rules
from app.paper.models import PaperAccount, PaperReplay, PaperTrade
from app.reports.schemas import (
    JOURNAL_LIMIT,
    PaperReportOut,
    ReportDayOut,
    ReportEmptyOut,
    ReportOpenPositionOut,
    ReportPeriodOut,
    ReportReadyOut,
    ReportReconciliationOut,
    ReportStrategyOut,
    ReportStrategyRefOut,
    ReportSummaryOut,
    ReportTradeOut,
)

IST = timezone(timedelta(hours=5, minutes=30), "IST")

CSV_HEADER = (
    "date",
    "filled_at",
    "replay",
    "strategy",
    "version",
    "instrument",
    "side",
    "quantity",
    "fill_inr",
    "fees_inr",
    "pnl_inr",
    "reason",
    "trade_id",
)
CSV_FILENAME = "tradeo-paper-trades.csv"
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def unavailable() -> ApiError:
    return ApiError(
        503, "REPORTS_UNAVAILABLE", "Reports are temporarily unavailable. Try again shortly."
    )


def invalid_period() -> ApiError:
    return ApiError(400, "INVALID_REQUEST", "The start date must not be after the end date.")


def ist_date(at: datetime) -> date:
    return at.astimezone(IST).date()


def inr(amount_paise: int) -> str:
    """Exact rupees with two decimals and no grouping: -123450 -> '-1234.50'."""
    sign = "-" if amount_paise < 0 else ""
    whole, fraction = divmod(abs(amount_paise), 100)
    return f"{sign}{whole}.{fraction:02d}"


def _is_number(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def csv_safe(value: str) -> str:
    """Prefix text a spreadsheet would run as a formula (contract: = + - @)."""
    if value.startswith(_FORMULA_PREFIXES) and not _is_number(value):
        return "'" + value
    return value


# IST session date of a fill, computed in the database.
_DAY: ColumnElement[date] = cast(func.timezone("Asia/Kolkata", PaperTrade.filled_at), Date)
_SELL = PaperTrade.side == "Sell"


@dataclass(frozen=True)
class _Period:
    start: date | None
    end: date | None

    def where(self, user_id: uuid.UUID) -> list[ColumnElement[bool]]:
        clauses: list[ColumnElement[bool]] = [PaperTrade.user_id == user_id]
        # date.min and date.max bound nothing; skipping them also avoids
        # building a datetime outside the supported range.
        if self.start is not None and self.start > date.min:
            clauses.append(PaperTrade.filled_at >= datetime.combine(self.start, time(), IST))
        if self.end is not None and self.end < date.max:
            next_day = self.end + timedelta(days=1)
            clauses.append(PaperTrade.filled_at < datetime.combine(next_day, time(), IST))
        return clauses


def _ref(
    strategy_id: uuid.UUID | None, name: str | None, version: int | None
) -> ReportStrategyRefOut | None:
    if strategy_id is None or name is None or version is None:
        return None
    return ReportStrategyRefOut(id=str(strategy_id), name=name, version=version)


def _replay_join() -> Any:
    return and_(PaperReplay.user_id == PaperTrade.user_id, PaperReplay.replay == PaperTrade.replay)


class ReportService:
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
        # Paper replays use the deterministic demo candles, so the open
        # position is marked with them too.
        self._market = DemoMarketDataProvider()

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _check(self, start: date | None, end: date | None) -> _Period:
        if not self._enabled:
            raise unavailable()
        if start is not None and end is not None and start > end:
            raise invalid_period()
        return _Period(start, end)

    # ------------------------------------------------------------- report

    async def paper_report(
        self, user_id: uuid.UUID, start: date | None, end: date | None
    ) -> ReportReadyOut | ReportEmptyOut:
        period = self._check(start, end)
        async with self._factory() as db, db.begin():
            await begin_consistent_read(db)
            account = await db.get(PaperAccount, user_id)
            if account is None or account.replay == 0:
                # No assignment ever means no fill either (fills need a replay).
                return ReportEmptyOut()
            where = period.where(user_id)
            daily = await self._daily(db, where)
            strategies = await self._strategies(db, where)
            journal_rows = await self._journal(db, where, JOURNAL_LIMIT + 1)
            wins, losses = await self._wins_losses(db, where)
            reconciliation = await self._reconciliation(db, account)
            open_position = await self._open_position(account)
            as_of = self._clock()

        realised = sum(d.realised_paise for d in daily)
        unrealised = 0 if open_position is None else open_position.unrealised_paise
        closed = sum(s.closed_trades for s in strategies)
        summary = ReportSummaryOut(
            realised_paise=realised,
            unrealised_paise=unrealised,
            net_paise=realised + unrealised,
            fees_paise=sum(d.fees_paise for d in daily),
            fills=sum(d.fills for d in daily),
            closed_trades=closed,
            winning_trades=wins,
            losing_trades=losses,
        )
        dates = [d.date for d in daily]
        report = PaperReportOut(
            as_of=as_of,
            period=ReportPeriodOut(
                from_=start if start is not None else (dates[0] if dates else None),
                to=end if end is not None else (dates[-1] if dates else None),
            ),
            summary=summary,
            open_position=open_position,
            daily=daily,
            strategies=strategies,
            journal=[_trade_out(*row) for row in journal_rows[:JOURNAL_LIMIT]],
            journal_truncated=len(journal_rows) > JOURNAL_LIMIT,
            reconciliation=reconciliation,
        )
        return ReportReadyOut(data=report)

    async def _daily(
        self, db: AsyncSession, where: list[ColumnElement[bool]]
    ) -> list[ReportDayOut]:
        rows = await db.execute(
            select(
                _DAY,
                func.sum(PaperTrade.pnl_paise),
                func.sum(PaperTrade.fees_paise),
                func.count(),
            )
            .where(*where)
            .group_by(_DAY)
            .order_by(_DAY)
        )
        return [
            ReportDayOut(date=day, realised_paise=int(pnl), fees_paise=int(fees), fills=fills)
            for day, pnl, fees, fills in rows.all()
        ]

    async def _strategies(
        self, db: AsyncSession, where: list[ColumnElement[bool]]
    ) -> list[ReportStrategyOut]:
        rows = await db.execute(
            select(
                PaperReplay.strategy_id,
                PaperReplay.strategy_name,
                PaperReplay.version_number,
                func.sum(PaperTrade.pnl_paise),
                func.sum(PaperTrade.fees_paise),
                func.count(),
                func.count().filter(_SELL),
            )
            .select_from(PaperTrade)
            .outerjoin(PaperReplay, _replay_join())
            .where(*where)
            .group_by(
                PaperReplay.strategy_id, PaperReplay.strategy_name, PaperReplay.version_number
            )
        )
        out = [
            ReportStrategyOut(
                strategy=_ref(sid, name, version),
                realised_paise=int(pnl),
                fees_paise=int(fees),
                fills=fills,
                closed_trades=closed,
            )
            for sid, name, version, pnl, fees, fills, closed in rows.all()
        ]
        # Name then version; unattributed fills last. The id breaks ties
        # between two strategies with the same name.
        out.sort(
            key=lambda s: (
                s.strategy is None,
                "" if s.strategy is None else s.strategy.name,
                0 if s.strategy is None else s.strategy.version,
                "" if s.strategy is None else s.strategy.id,
            )
        )
        return out

    async def _wins_losses(
        self, db: AsyncSession, where: list[ColumnElement[bool]]
    ) -> tuple[int, int]:
        row = (
            await db.execute(
                select(
                    func.count().filter(and_(_SELL, PaperTrade.pnl_paise > 0)),
                    func.count().filter(and_(_SELL, PaperTrade.pnl_paise < 0)),
                ).where(*where)
            )
        ).one()
        return int(row[0]), int(row[1])

    async def _journal(
        self, db: AsyncSession, where: list[ColumnElement[bool]], limit: int | None
    ) -> Sequence[Any]:
        query = (
            select(
                PaperTrade,
                PaperReplay.strategy_id,
                PaperReplay.strategy_name,
                PaperReplay.version_number,
            )
            .outerjoin(PaperReplay, _replay_join())
            .where(*where)
        )
        if limit is None:
            query = query.order_by(PaperTrade.seq.asc())
        else:
            query = query.order_by(PaperTrade.seq.desc()).limit(limit)
        return (await db.execute(query)).all()

    async def _reconciliation(
        self, db: AsyncSession, account: PaperAccount
    ) -> ReportReconciliationOut:
        gross = PaperTrade.fill_paise * PaperTrade.quantity
        row = (
            await db.execute(
                select(
                    func.coalesce(
                        func.sum(
                            case(
                                (_SELL, gross - PaperTrade.fees_paise),
                                else_=-(gross + PaperTrade.fees_paise),
                            )
                        ),
                        0,
                    ),
                    func.coalesce(
                        func.sum(case((_SELL, -PaperTrade.quantity), else_=PaperTrade.quantity)),
                        0,
                    ),
                ).where(PaperTrade.user_id == account.user_id, PaperTrade.replay == account.replay)
            )
        ).one()
        ledger_cash = account.capital_paise + int(row[0])
        ledger_quantity = int(row[1])
        matched = ledger_cash == account.cash_paise and ledger_quantity == account.position_quantity
        return ReportReconciliationOut(
            status="matched" if matched else "mismatch",
            replay=account.replay,
            ledger_cash_paise=ledger_cash,
            account_cash_paise=account.cash_paise,
            ledger_quantity=ledger_quantity,
            account_quantity=account.position_quantity,
        )

    async def _open_position(self, account: PaperAccount) -> ReportOpenPositionOut | None:
        entry = account.position_entry_paise
        if (
            account.position_quantity == 0
            or entry is None
            or account.instrument_id is None
            or account.sessions_done == 0
        ):
            return None
        candles = await self._market.get_candles(account.instrument_id, "1D")
        if candles is None or len(candles.candles) < account.sessions_done:
            return None  # pragma: no cover - the demo history does not shrink
        last = candles.candles[account.sessions_done - 1]
        mark = rules.paise(last.close)
        quantity = account.position_quantity
        instrument = next(
            (
                i.symbol
                for i in await self._market.list_instruments()
                if i.id == account.instrument_id
            ),
            account.instrument_id,
        )
        return ReportOpenPositionOut(
            instrument=instrument,
            quantity=quantity,
            entry_paise=entry,
            mark_paise=mark,
            marked_at=last.time,
            unrealised_paise=(mark - entry) * quantity - account.position_fees_paise,
        )

    # ---------------------------------------------------------------- CSV

    async def paper_trades_csv(
        self, user_id: uuid.UUID, start: date | None, end: date | None
    ) -> str:
        period = self._check(start, end)
        async with self._factory() as db, db.begin():
            await begin_consistent_read(db)
            rows = await self._journal(db, period.where(user_id), None)
        out = io.StringIO()
        writer = csv.writer(out, lineterminator="\r\n")
        writer.writerow(CSV_HEADER)
        for trade, sid, name, version in rows:
            attributed = sid is not None and name is not None and version is not None
            writer.writerow(
                [
                    ist_date(trade.filled_at).isoformat(),
                    trade.filled_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                    trade.replay,
                    csv_safe(name) if attributed else "",
                    version if attributed else "",
                    csv_safe(trade.instrument),
                    trade.side,
                    trade.quantity,
                    inr(trade.fill_paise),
                    inr(trade.fees_paise),
                    inr(trade.pnl_paise),
                    trade.reason,
                    str(trade.id),
                ]
            )
        return out.getvalue()


def _trade_out(
    trade: PaperTrade, sid: uuid.UUID | None, name: str | None, version: int | None
) -> ReportTradeOut:
    return ReportTradeOut(
        id=str(trade.id),
        date=ist_date(trade.filled_at),
        replay=trade.replay,
        strategy=_ref(sid, name, version),
        instrument=trade.instrument,
        side=trade.side,
        quantity=trade.quantity,
        fill_paise=trade.fill_paise,
        fees_paise=trade.fees_paise,
        pnl_paise=trade.pnl_paise,
        filled_at=trade.filled_at,
        reason=trade.reason,
    )
