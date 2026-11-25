// @vitest-environment node
import { describe, expect, it } from "vitest";
import { applyPaperCommand, canStartPaper, createPaperTradingMock } from "@/lib/api/auto-trading-mock";
import type { PaperTradingClient } from "@/lib/api/auto-trading-types";
import { getPaperTradeControls } from "@/lib/paper-trade-controls";

async function load(client: PaperTradingClient) {
  const result = await client.getPaperTrading();
  if (result.status !== "ready") throw new Error("Expected a ready paper snapshot");
  return result.data;
}

describe("paper trading simulator", () => {
  it("starts idle in paper mode and rejects starts blocked by risk or readiness", async () => {
    const snapshot = await load(createPaperTradingMock());
    expect(snapshot).toMatchObject({ environment: "PAPER", source: "demo", engine: "idle" });
    expect(canStartPaper(snapshot)).toBe(true);

    const blocked = { ...snapshot, risk: { ...snapshot.risk, status: "blocked" as const } };
    const atLimit = { ...snapshot, risk: { ...snapshot.risk, dailyLossPaise: snapshot.risk.lossLimitPaise } };
    const unavailable = { ...snapshot, agent: { ...snapshot.agent, ready: false } };
    for (const input of [blocked, atLimit, unavailable, { ...snapshot, strategyId: null }]) {
      expect(() => applyPaperCommand(input, { action: "start" })).toThrow("not ready");
    }
  });

  it("assigns strategies while idle and appends an event per change", async () => {
    const initial = await load(createPaperTradingMock());
    const assigned = applyPaperCommand(initial, { action: "assign", strategyId: "bank-range" });
    const running = applyPaperCommand(assigned, { action: "start" });
    expect(assigned.strategyId).toBe("bank-range");
    expect(initial.strategyId).toBe("nifty-momentum");
    expect(running.events).toHaveLength(initial.events.length + 2);
    expect(running.events.slice(0, initial.events.length)).toEqual(initial.events);
    expect(running.events.at(-1)?.message).toBe("Paper engine started.");
    expect(() => applyPaperCommand(running, { action: "assign", strategyId: "nifty-momentum" })).toThrow();
    expect(applyPaperCommand(running, { action: "pause" }).engine).toBe("idle");
  });

  it("uses the preview's IST date and holds a triggered loss streak through a later win", async () => {
    const initial = await load(createPaperTradingMock());
    const fill = initial.trades[0];
    const snapshot = {
      ...initial,
      asOf: "2026-11-23T02:30:00Z",
      risk: { ...initial.risk, maxConsecutiveLosses: 2 },
      trades: [
        { ...fill, filledAt: "2026-11-23T01:30:00Z", pnlPaise: 400 },
        { ...fill, filledAt: "2026-11-22T18:29:00Z", pnlPaise: -10_000 },
        { ...fill, filledAt: "2026-11-23T02:31:00Z", pnlPaise: 10_000 },
        { ...fill, filledAt: "2026-11-22T18:30:00Z", pnlPaise: -100 },
        { ...fill, filledAt: "2026-11-23T00:30:00Z", pnlPaise: -100 },
      ],
    };
    expect(getPaperTradeControls(snapshot)).toMatchObject({
      netPaise: 200, peakPaise: 200, limitReached: expect.stringContaining("Consecutive loss limit reached"),
    });
    expect(canStartPaper({ ...snapshot, risk: { ...snapshot.risk, maxConsecutiveLosses: 0 } })).toBe(true);
    expect(canStartPaper({ ...snapshot, asOf: "2026-11-23T18:30:00Z" })).toBe(true);
  });

  it("requires post-cap confidence and rejects invalid or unsizeable demo entries", async () => {
    const initial = await load(createPaperTradingMock());
    const limits = {
      ...initial.risk, profitLimitPaise: 58_000, postCapConfidencePercent: 75,
    };
    const atCap = applyPaperCommand(initial, { action: "set-limits", limits });
    expect(canStartPaper(atCap)).toBe(true);
    expect(canStartPaper({ ...atCap, sampleEntry: { ...atCap.sampleEntry, confidencePercent: null } })).toBe(false);
    const small = applyPaperCommand(atCap, { action: "set-limits", limits: { ...limits, maxRiskPerTradePaise: 1 } });
    expect(getPaperTradeControls(small)).toMatchObject({ maxQuantity: 0, limitReached: expect.stringContaining("sizing limits") });
    expect(canStartPaper(small)).toBe(false);
    expect(() => applyPaperCommand(initial, { action: "set-limits", limits: { ...limits, stopLossBps: 0 } })).toThrow("stop loss");
    const running = applyPaperCommand(initial, { action: "start" });
    expect(() => applyPaperCommand(running, { action: "set-limits", limits })).toThrow("Pause the paper engine");
  });

  it("cancels the queue on confirmed halt without changing completed trades", async () => {
    const initial = await load(createPaperTradingMock());
    const running = applyPaperCommand(initial, { action: "start" });
    const halted = applyPaperCommand(running, { action: "halt", confirmation: "STOP" });
    expect(halted.engine).toBe("halted");
    expect(halted.orders.map(({ status }) => status)).toEqual(["cancelled", "cancelled"]);
    expect(initial.orders.map(({ status }) => status)).toEqual(["queued", "held"]);
    expect(halted.trades).toEqual(initial.trades);
    expect(halted.events.at(-1)?.message).toContain("Cancelled 2 pending paper orders");
    expect(() => applyPaperCommand(halted, { action: "start" })).toThrow();
    const reset = applyPaperCommand(halted, { action: "reset" });
    expect(reset.engine).toBe("idle");
    expect(reset.orders).toEqual(halted.orders);
  });

  it("rejects commands on stale or denied access and isolates demo sessions", async () => {
    const client = createPaperTradingMock();
    const otherSession = createPaperTradingMock();

    await Promise.all([
      expect(client.getPaperTrading({ scenario: "empty" })).resolves.toEqual({ status: "empty" }),
      expect(client.getPaperTrading({ scenario: "denied" })).resolves.toEqual({ status: "denied" }),
      expect(client.getPaperTrading({ scenario: "stale" })).resolves.toMatchObject({ status: "stale" }),
      expect(client.getPaperTrading({ scenario: "error" })).rejects.toThrow("Simulated"),
      expect(client.sendPaperCommand({ action: "start" }, { scenario: "stale" })).rejects.toThrow("Fresh paper data"),
      expect(client.sendPaperCommand({ action: "start" }, { scenario: "denied" })).rejects.toThrow("Fresh paper data"),
    ]);

    await client.sendPaperCommand({ action: "start" });
    expect((await load(client)).engine).toBe("running");
    expect((await load(otherSession)).engine).toBe("idle");
  });
});
