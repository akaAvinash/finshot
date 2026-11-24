import { describe, expect, it } from "vitest";
import { createBacktestMock, exampleBacktestConfig } from "@/lib/api/backtest-mock";
import type { MarketCandle } from "@/lib/api/market-types";
import { backtestTradesCsv, replayDemoBacktest, validateBacktestConfig } from "@/lib/backtesting";

const config = {
  ...exampleBacktestConfig, from: "2026-10-05", outOfSampleFrom: "2026-10-08", to: "2026-10-12",
  capitalPaise: 1_000_000, feeBps: 10, slippageBps: 25,
};

const candles: MarketCandle[] = [
  ["05", 100, 100], ["06", 100, 101], ["07", 101, 102], ["08", 104, 110], ["09", 107, 50], ["12", 70, 90],
].map(([day, open, close]) => ({
  time: `2026-10-${day}T03:45:00.000Z`, open: Number(open), close: Number(close),
  high: Math.max(Number(open), Number(close)), low: Math.min(Number(open), Number(close)), volume: null,
}));

describe("demo backtest replay", () => {
  it("fills at a later open and keeps warm-up data out of results", () => {
    const result = replayDemoBacktest(config, candles, 5000);
    expect(result.points.map(({ date }) => date)).toEqual(["2026-10-08", "2026-10-09", "2026-10-12"]);
    expect(result.trades).toHaveLength(1);
    const [trade] = result.trades;
    expect(trade).toMatchObject({ entryAt: candles[3].time, exitAt: candles[5].time, entryPaise: 10426, exitPaise: 6982 });
    expect(trade.feesPaise).toBe(820);
    expect(result.totalFeesPaise).toBe(820);
    expect(result.endingEquityPaise).toBe(config.capitalPaise + trade.pnlPaise);
    expect(result.netPnlPaise).toBe(trade.pnlPaise);
    expect(result.maxDrawdownBps).toBeLessThan(0);

    const differentFirstHoldoutClose = candles.map((bar, index) => index === 3 ? { ...bar, close: 90 } : bar);
    const changed = replayDemoBacktest(config, differentFirstHoldoutClose, 5000);
    expect(changed.trades[0]).toMatchObject({ entryAt: trade.entryAt, entryPaise: trade.entryPaise, quantity: trade.quantity });
  });

  it("closes at the final session open even when the signal stays long", () => {
    const rising = candles.map((bar, index) => index === 4 ? { ...bar, close: 115, high: 115 } : bar);
    const result = replayDemoBacktest(config, rising, 5000);
    expect(result.trades).toHaveLength(1);
    expect(result.trades[0]).toMatchObject({ entryAt: candles[3].time, exitAt: candles[5].time, exitPaise: 6982 });
    expect(result.endingEquityPaise).toBe(config.capitalPaise + result.trades[0].pnlPaise);
  });

  it("handles zero fills and rejects bad windows and costs", () => {
    const result = replayDemoBacktest({ ...config, capitalPaise: 100_000 }, candles, 1);
    expect(result).toMatchObject({ endingEquityPaise: 100_000, netPnlPaise: 0, winRateBps: null, trades: [] });
    expect(validateBacktestConfig({ ...config, outOfSampleFrom: "2026-02-30" }, config)).toMatch(/valid dates/);
    expect(validateBacktestConfig({ ...config, feeBps: 0.1 }, config)).toMatch(/whole basis points/);
    expect(() => replayDemoBacktest({ ...config, outOfSampleFrom: "2026-10-06" }, candles, 5000)).toThrow(/warm-up sessions/);
  });

  it("supports an empty queue, deterministic progress, failed jobs, and demo CSV", async () => {
    let time = 0;
    const client = createBacktestMock({ delay: 0, now: () => time });
    await expect(client.getBacktestWorkspace({ scenario: "empty" })).resolves.toMatchObject({ status: "ready", data: { runs: [] } });
    const queued = await client.startBacktest(exampleBacktestConfig, { scenario: "empty" });
    expect(queued).toMatchObject({ id: "backtest-1", status: "queued", environment: "DEMO" });
    time = 400;
    await expect(client.getBacktestRun(queued.id)).resolves.toMatchObject({ status: "running" });
    time = 1200;
    const run = await client.getBacktestRun(queued.id);
    expect(run.status).toBe("completed");
    if (run.status !== "completed") throw new Error("Expected demo results.");
    expect(run.result.trades.length).toBeGreaterThan(0);
    expect(backtestTradesCsv(run)).toContain("DEMO,backtest-1,NSE:NIFTY50,");
    const failed = await client.startBacktest(exampleBacktestConfig, { scenario: "run-error" });
    time += 1200;
    await expect(client.getBacktestRun(failed.id)).resolves.toMatchObject({ status: "failed" });
    await expect(client.startBacktest(exampleBacktestConfig, { scenario: "stale" })).rejects.toThrow(/current workspace/);
  });
});
