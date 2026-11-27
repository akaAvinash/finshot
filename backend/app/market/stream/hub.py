"""The market stream hub: one upstream connection, many owner connections.

The hub runs the source's `run` loop under a supervisor that reconnects with
bounded exponential backoff, keeps the latest tick per instrument, and fans
ticks out to subscribers through bounded queues. A subscriber whose queue
fills is marked `overflowed`; its WebSocket closes with 1013. The hub never
touches orders: it has no order state, queue or connection."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime

import structlog

from app.market.stream.source import Subscriptions, TickSource
from app.market.stream.ticks import FeedState, Tick, market_hours

logger = structlog.get_logger(__name__)

Clock = Callable[[], datetime]


class Subscriber:
    def __init__(self, instrument_id: str, queue_size: int) -> None:
        self.instrument_id = instrument_id
        self.queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=queue_size)
        self.overflowed = asyncio.Event()

    def offer(self, tick: Tick) -> None:
        if self.overflowed.is_set():
            return
        try:
            self.queue.put_nowait(tick)
        except asyncio.QueueFull:
            self.overflowed.set()


class MarketStreamHub:
    def __init__(
        self,
        source: TickSource,
        *,
        clock: Clock,
        queue_size: int = 256,
        stale_after_seconds: float = 30.0,
        max_backoff_seconds: float = 60.0,
    ) -> None:
        self.source = source
        self._clock = clock
        self._queue_size = queue_size
        self._stale_after = stale_after_seconds
        self._max_backoff = max_backoff_seconds
        self._wanted = Subscriptions()
        self._subscribers: dict[str, set[Subscriber]] = {}
        self._latest: dict[str, Tick] = {}
        self._tick_events: dict[str, asyncio.Event] = {}
        self._connected = False
        self._last_message: datetime | None = None
        self._task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._supervise())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._connected = False

    async def _supervise(self) -> None:
        delay = 1.0
        while True:
            started = self._clock()
            try:
                await self.source.run(self._wanted, self._emit, self._heartbeat)
                logger.warning("market_stream_upstream_ended")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # Type only: provider errors can carry URLs with credentials.
                logger.warning("market_stream_upstream_failed", error_type=type(exc).__name__)
            self._connected = False
            # A connection that held for a while resets the backoff.
            if (self._clock() - started).total_seconds() > 60:
                delay = 1.0
            await asyncio.sleep(delay)
            delay = min(delay * 2, self._max_backoff)

    # --------------------------------------------------------------- upstream

    def _heartbeat(self) -> None:
        self._connected = True
        self._last_message = self._clock()

    def _emit(self, tick: Tick) -> None:
        self._heartbeat()
        previous = self._latest.get(tick.instrument_id)
        if previous is not None and tick.exchange_time < previous.exchange_time:
            return  # older than what subscribers already have
        self._latest[tick.instrument_id] = tick
        event = self._tick_events.get(tick.instrument_id)
        if event is not None:
            event.set()
        for subscriber in tuple(self._subscribers.get(tick.instrument_id, ())):
            subscriber.offer(tick)

    # ------------------------------------------------------------ subscribers

    def state(self) -> FeedState:
        now = self._clock()
        if not self._connected or self._last_message is None:
            return "unavailable"
        if not self.source.always_open and not market_hours(now):
            return "closed"
        if (now - self._last_message).total_seconds() > self._stale_after:
            return "stale"
        return "live"

    def now(self) -> datetime:
        return self._clock()

    def latest(self, instrument_id: str) -> Tick | None:
        return self._latest.get(instrument_id)

    @property
    def connection_count(self) -> int:
        return sum(len(group) for group in self._subscribers.values())

    @asynccontextmanager
    async def subscribe(self, instrument_id: str) -> AsyncIterator[Subscriber]:
        subscriber = Subscriber(instrument_id, self._queue_size)
        group = self._subscribers.setdefault(instrument_id, set())
        group.add(subscriber)
        self._wanted.set(set(self._subscribers))
        try:
            yield subscriber
        finally:
            group.discard(subscriber)
            if not group:
                del self._subscribers[instrument_id]
                self._tick_events.pop(instrument_id, None)
                # A later subscriber must wait for a fresh tick, not get one
                # left over from before.
                self._latest.pop(instrument_id, None)
            self._wanted.set(set(self._subscribers))

    async def wait_for_tick(self, instrument_id: str, *, wait_seconds: float) -> Tick | None:
        """The latest tick for a subscribed instrument, waiting up to
        `wait_seconds` for the first one. None when none arrives in time."""
        tick = self._latest.get(instrument_id)
        if tick is not None:
            return tick
        event = self._tick_events.setdefault(instrument_id, asyncio.Event())
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(wait_seconds):
                await event.wait()
        return self._latest.get(instrument_id)
