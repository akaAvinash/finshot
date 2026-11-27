import { randomUUID } from "node:crypto";
import { createContractWorkspaceFixture } from "./contract-workspace-fixture.mjs";

const api = "/api/v1";
const asOf = "2026-11-23T10:00:00Z";
const demo = { source: "demo", environment: "DEMO", asOf };
const paper = { source: "demo", environment: "PAPER", asOf };
const ready = (data) => [200, { status: "ready", data }];
const rejected = (message) => [409, { code: "CONFLICT", message }];
const instrument = { id: "NSE:NIFTY50", symbol: "NIFTY 50" };
const agents = [
  { id: "market-scanner", name: "Market Scanner" },
  { id: "strategy-analyst", name: "Strategy Analyst" },
  { id: "risk-explainer", name: "Risk Explainer" },
  { id: "execution-monitor", name: "Execution Monitor" },
].map((agent) => ({ ...agent, role: "advisory", description: "Observes the paper replay." }));
const risk = { dailyLossPaise: 15000, tradesToday: 0, consecutiveLosses: 0 };
const account = { capitalPaise: 2500000, cashPaise: 2500000, equityPaise: 2500000, positionQuantity: 0, perTradeRiskPaise: 75000 };

export function createWorkspaceFixture() {
  const accounts = new Map();
  const contract = createContractWorkspaceFixture();
  let rejectBroker = false;

  function handle(url, owner, body, steppedUp) {
    if (!accounts.has(owner)) accounts.set(owner, { connections: [], brokerEvents: [], strategies: [], runs: [], testedDrafts: new Map(), paperState: null });
    const state = accounts.get(owner);
    const path = url.pathname.slice(api.length + 1);
    const newContract = contract.handle(path, owner, body, steppedUp, state.paperState?.engine);
    if (newContract) return newContract;
    const brokers = () => ({ ...demo, events: state.brokerEvents, connections: ["zerodha", "fyers"].map((provider) => ({
      provider, account: state.connections.find((row) => row.provider === provider)?.account ?? null,
    })) });
    const strategies = () => ({ ...demo, strategies: state.strategies });
    const active = () => state.strategies.filter(({ status }) => status === "active").map(({ id, versions }) => {
      const latest = versions.at(-1);
      return { id, name: latest.parameters.name, instrument: latest.parameters.instrument, version: latest.number };
    });
    const settings = contract.settings(owner);
    const halted = state.paperState?.engine === "halted";
    const paperSnapshot = () => ({ ...paper, strategies: active(), agent: { name: "Paper execution agent", ready: !!state.paperState?.strategyId },
      account: { ...account, perTradeRiskPaise: settings.controls.maxRiskPerTradePaise }, risk: { ...risk,
        status: halted ? "blocked" : "approved", blockedReason: halted ? "HALTED" : null,
        tradeLimit: settings.controls.tradeLimit, lossLimitPaise: settings.controls.lossLimitPaise,
        controlsRevision: settings.revision, tradesToday: state.paperState?.trades.length ?? 0 }, engine: "idle", strategyId: null,
      replay: { sessionDate: null, sessionsDone: 0, sessionsTotal: 0, finished: false }, orders: [], trades: [], events: [], ...state.paperState });

    if (path === "brokers/preview") return ready(brokers());
    const broker = /^brokers\/preview\/(zerodha|fyers)\/actions$/.exec(path)?.[1];
    if (broker) {
      if (rejectBroker) {
        rejectBroker = false;
        return rejected("The broker connection changed. Refresh before trying again.");
      }
      const existing = state.connections.find(({ provider }) => provider === broker);
      if (body.action === "disconnect") state.connections = state.connections.filter(({ provider }) => provider !== broker);
      else if (body.action === "sync" && existing) existing.account.lastSyncedAt = asOf;
      else state.connections.push({ provider: broker, account: {
        maskedAccountId: "•••• 0248", connectedAt: asOf, expiresAt: "2026-12-01T10:00:00Z", lastSyncedAt: null, scopes: ["profile_read"],
      } });
      state.brokerEvents.push({ id: randomUUID(), provider: broker, action: body.action, at: asOf });
      return [200, brokers()];
    }

    if (path === "strategies/preview") return ready(strategies());
    if (path === "strategies/preview/commands") {
      const draft = { parameters: body.parameters, backtest: "unavailable", riskReview: "approved" };
      const row = state.strategies.find(({ id }) => id === body.id);
      if (body.action === "create") state.strategies.push({ id: randomUUID(), status: "draft", draft, versions: [], metrics: null });
      else if (!row) return rejected("Select an existing strategy.");
      else if (body.action === "save-draft") row.draft = draft;
      else if (body.action === "pause") row.status = "paused";
      else if (body.action === "activate") {
        if (row.draft?.backtest !== "passed") return rejected("A passing backtest for this revision is required.");
        row.versions.push({ ...row.draft, number: row.versions.length + 1, activatedAt: asOf });
        row.draft = null;
        row.status = "active";
      }
      return [200, strategies()];
    }

    if (path === "backtests/preview") return ready({
      ...demo, from: "2026-10-01", to: "2026-11-23", instruments: [instrument], runs: state.runs,
      strategies: state.strategies.filter(({ draft }) => draft).map(({ id, draft }) => ({
        id: `${id}:draft`, revision: "draft", name: draft.parameters.name, instrumentId: instrument.id, positionSizeBps: draft.parameters.positionSizeBps,
      })),
    });
    if (path === "backtests/preview/runs") {
      const draft = state.strategies.find(({ id, draft }) => draft && `${id}:draft` === body.strategyId)?.draft;
      if (!draft) return rejected("Select a current strategy revision.");
      const run = { ...demo, id: randomUUID(), config: body, queuedAt: asOf, status: "queued" };
      state.testedDrafts.set(run.id, draft.parameters);
      state.runs.unshift(run);
      return [202, run];
    }
    if (path.startsWith("backtests/preview/runs/")) {
      const run = state.runs.find(({ id }) => id === path.split("/").at(-1));
      if (!run) return [404, { code: "NOT_FOUND", message: "This backtest run could not be found." }];
      if (run.status === "queued") run.status = "running";
      else if (run.status === "running") {
        run.status = "completed";
        run.result = { endingEquityPaise: 50133400, netPnlPaise: 133400, returnBps: 27, maxDrawdownBps: -10,
          winRateBps: 10000, totalFeesPaise: 1600,
          points: [{ date: "2026-10-21", equityPaise: 50000000, drawdownBps: 0 }, { date: "2026-11-23", equityPaise: 50133400, drawdownBps: 0 }],
          trades: [{ id: "backtest-trade", entryAt: "2026-10-22T10:00:00Z", exitAt: asOf, quantity: 5, entryPaise: 2270000, exitPaise: 2297000, feesPaise: 1600, pnlPaise: 133400 }] };
        const row = state.strategies.find(({ id }) => `${id}:draft` === run.config.strategyId);
        if (row?.draft && JSON.stringify(row.draft.parameters) === JSON.stringify(state.testedDrafts.get(run.id))) {
          row.draft.backtest = "passed";
        }
        state.testedDrafts.delete(run.id);
      }
      return [200, run];
    }

    if (path === "auto-trading/paper") {
      const replay = state.paperState;
      if (replay?.engine === "running" && !replay.trades.length) {
        replay.replay = { sessionDate: "2026-10-22", sessionsDone: 8, sessionsTotal: 38, finished: false };
        replay.orders.push({ id: "order-1", instrument: instrument.symbol, side: "Buy", quantity: 1, limitPaise: 2300000, approval: "approved", status: "filled" });
        replay.trades.push({ id: "fill-1", instrument: instrument.symbol, side: "Buy", quantity: 1, fillPaise: 2300000, feesPaise: 690, pnlPaise: 0, reason: "entry", filledAt: asOf });
      }
      return state.paperState || active().length ? ready(paperSnapshot()) : [200, { status: "empty" }];
    }
    if (path === "auto-trading/paper/commands") {
      if (body.action === "assign" && active().some(({ id }) => id === body.strategyId)) {
        state.paperState = { engine: "idle", strategyId: body.strategyId, orders: [], trades: [], events: [] };
      } else if (body.action === "start" && state.paperState?.engine === "idle") state.paperState.engine = "running";
      else if (body.action === "pause" && state.paperState?.engine === "running") state.paperState.engine = "idle";
      else if (body.action === "halt" && body.confirmation === "STOP" && state.paperState?.engine !== "halted" && state.paperState) {
        state.paperState.engine = "halted";
        for (const order of state.paperState.orders) if (order.status === "queued") order.status = "cancelled";
      } else if (body.action === "reset" && state.paperState?.engine === "halted") state.paperState.engine = "idle";
      else return rejected("The paper engine cannot accept that command.");
      return [200, paperSnapshot()];
    }
    if (path === "agents") return [200, { ...paper, agents }];
    if (path === "agents/health") return [200, { ...paper, status: "degraded", agents: agents.map(({ id }) => ({
      agentId: id, status: id === "market-scanner" ? "stale" : "ok", reasonCode: id === "market-scanner" ? "DATA_STALE" : null, lastRunAt: asOf,
    })) }];
    if (path === "agents/events") {
      const item = { id: "agent-event-1", agentId: "market-scanner", severity: "info", reasonCode: "LARGE_MOVE", at: asOf, dataAsOf: asOf,
        message: "A large move was observed in the demo replay.", recommendation: null };
      const agent = url.searchParams.get("agentId");
      const older = url.searchParams.has("cursor");
      const items = !agent || agent === item.agentId ? [older ? { ...item, id: "agent-event-2", message: "An earlier demo observation." } : item] : [];
      return [200, { ...paper, items, nextCursor: items.length && !older ? "fixture-older-events" : null }];
    }
    return [404, { code: "NOT_FOUND", message: "Fixture endpoint unavailable." }];
  }

  return { handle, rejectNextBrokerCommand: () => { rejectBroker = true; contract.rejectNextAction(); } };
}
