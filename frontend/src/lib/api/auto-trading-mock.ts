import { getPaperTradeControls, validatePaperLimits } from "../paper-trade-controls";
import type { PaperCommand, PaperSnapshot, PaperTradingClient } from "./auto-trading-types";
import { waitForMock } from "./mock-delay";

const fixture: PaperSnapshot = {
  source: "demo",
  environment: "PAPER",
  asOf: "2026-11-23T09:55:00.000Z",
  engine: "idle",
  agent: { name: "Paper execution agent", ready: true },
  strategyId: "nifty-momentum",
  strategies: [
    { id: "nifty-momentum", name: "NIFTY Momentum", instrument: "NIFTY 50" },
    { id: "bank-range", name: "Bank Nifty Range", instrument: "BANKNIFTY" },
    { id: "equity-reversion", name: "Equity Mean Reversion", instrument: "RELIANCE" },
  ],
  sampleEntry: { pricePaise: 18_240, equityPaise: 10_000_000, confidencePercent: 75 },
  risk: {
    status: "approved", dailyLossPaise: 42_500, tradesToday: 3,
    profitLimitPaise: 500_000, lossLimitPaise: 250_000, tradeLimit: 10,
    postCapConfidencePercent: 70, maxConsecutiveLosses: 3,
    stopLossBps: 100, takeProfitBps: 200, maxRiskPerTradePaise: 50_000, maxPositionSizeBps: 1_000,
  },
  orders: [
    { id: "P-104", instrument: "NIFTY 50 24500 CE", side: "Buy", quantity: 75, limitPaise: 18_240, approval: "approved", status: "queued" },
    { id: "P-105", instrument: "BANKNIFTY 52300 PE", side: "Sell", quantity: 30, limitPaise: 47_825, approval: "pending", status: "held" },
  ],
  trades: [
    { id: "P-103", instrument: "HDFCBANK", side: "Buy", quantity: 100, fillPaise: 99_120, pnlPaise: -29_500, filledAt: "2026-11-23T08:41:00.000Z" },
    { id: "P-102", instrument: "SBIN", side: "Buy", quantity: 100, fillPaise: 85_020, pnlPaise: 71_000, filledAt: "2026-11-23T07:26:00.000Z" },
    { id: "P-101", instrument: "RELIANCE", side: "Sell", quantity: 50, fillPaise: 143_225, pnlPaise: -13_000, filledAt: "2026-11-23T05:32:00.000Z" },
  ],
  events: [
    { id: "event-1", at: "2026-11-23T03:45:00.000Z", message: "Paper preview session opened." },
    { id: "event-2", at: "2026-11-23T09:55:00.000Z", message: "Sample risk checks passed. One order is awaiting approval." },
  ],
};

export function canStartPaper(snapshot: PaperSnapshot) {
  return snapshot.engine === "idle" && snapshot.strategyId !== null && snapshot.agent.ready
    && !getPaperTradeControls(snapshot).limitReached;
}

export function applyPaperCommand(snapshot: PaperSnapshot, command: PaperCommand): PaperSnapshot {
  let change: Partial<PaperSnapshot>;
  let message: string;

  switch (command.action) {
    case "set-limits": {
      if (snapshot.engine !== "idle") throw new Error("Pause the paper engine before changing trade limits.");
      const error = validatePaperLimits(command.limits);
      if (error) throw new Error(error);
      const { status, dailyLossPaise, tradesToday } = snapshot.risk;
      change = { risk: { ...command.limits, status, dailyLossPaise, tradesToday } };
      message = "Demo trade limits updated.";
      break;
    }
    case "assign": {
      const strategy = snapshot.strategies.find(({ id }) => id === command.strategyId);
      if (!strategy || snapshot.engine !== "idle") throw new Error("Strategy assignment requires an idle paper engine.");
      if (strategy.id === snapshot.strategyId) return snapshot;
      change = { strategyId: strategy.id };
      message = `Assigned ${strategy.name}.`;
      break;
    }
    case "start":
      if (!canStartPaper(snapshot)) throw new Error("The paper engine is not ready to start.");
      change = { engine: "running" };
      message = "Paper engine started.";
      break;
    case "pause":
      if (snapshot.engine !== "running") throw new Error("The paper engine is not running.");
      change = { engine: "idle" };
      message = "Paper engine paused.";
      break;
    case "halt": {
      if (command.confirmation !== "STOP" || snapshot.engine === "halted") throw new Error("Paper halt confirmation is required.");
      const pending = snapshot.orders.filter(({ status }) => status !== "cancelled").length;
      change = { engine: "halted", orders: snapshot.orders.map((order) => ({ ...order, status: "cancelled" })) };
      message = `Paper kill switch activated. Cancelled ${pending} pending paper ${pending === 1 ? "order" : "orders"}.`;
      break;
    }
    case "reset":
      if (snapshot.engine !== "halted") throw new Error("The paper engine has no halt to clear.");
      change = { engine: "idle" };
      message = "Paper halt cleared. Engine remains idle.";
      break;
  }

  const asOf = new Date(Date.parse(snapshot.asOf) + 1000).toISOString();
  return {
    ...snapshot,
    ...change,
    asOf,
    events: [...snapshot.events, { id: `event-${snapshot.events.length + 1}`, at: asOf, message }],
  };
}

export function createPaperTradingMock(): PaperTradingClient {
  let snapshot = fixture;

  return {
    async getPaperTrading({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, 360);
      if (scenario === "error") throw new Error("Simulated paper workspace request failure.");
      if (scenario === "empty" || scenario === "denied") return { status: scenario };
      return { status: scenario, data: structuredClone(snapshot) };
    },
    async sendPaperCommand(command, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, 220);
      if (scenario !== "ready") throw new Error("Fresh paper data is required.");
      snapshot = applyPaperCommand(snapshot, command);
      return structuredClone(snapshot);
    },
  };
}
