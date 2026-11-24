import { BacktestInputError, replayDemoBacktest, validateBacktestConfig } from "../backtesting";
import { generateMarketCandles, marketFixture, marketSnapshotDate } from "./market-fixture";
import { waitForMock } from "./mock-delay";
import { createStrategyFixture } from "./strategy-fixture";
import type { BacktestClient, BacktestConfig, BacktestRun, BacktestStrategy } from "./backtest-types";
import type { StrategyParameters } from "./strategy-types";

const instruments = marketFixture.map(({ id, symbol }) => ({ id, symbol }));
const strategies = createStrategyFixture().strategies.flatMap((strategy): BacktestStrategy[] => {
  const revisions: { parameters: StrategyParameters; revision: number | "draft" }[] = strategy.versions.map(({ parameters, number }) => ({ parameters, revision: number }));
  if (strategy.draft) revisions.push({ parameters: strategy.draft.parameters, revision: "draft" });
  return revisions.flatMap(({ parameters, revision }) => {
    const instrument = instruments.find(({ symbol }) => symbol === parameters.instrument);
    if (!instrument) return [];
    return [{ id: `${strategy.id}-${revision}`, name: parameters.name, revision, instrumentId: instrument.id, positionSizeBps: parameters.positionSizeBps }];
  });
});

const range = { from: "2026-10-01", to: marketSnapshotDate().slice(0, 10) };
const workspaceBase = { source: "demo", environment: "DEMO", ...range, strategies, instruments } as const;
const baseAt = Date.parse(marketSnapshotDate());

export const exampleBacktestConfig: BacktestConfig = {
  strategyId: "nifty-momentum-2",
  instrumentId: "NSE:NIFTY50",
  from: "2026-10-05",
  to: range.to,
  outOfSampleFrom: "2026-10-21",
  capitalPaise: 50_000_000,
  feeBps: 8,
  slippageBps: 5,
};

type Completed = Extract<BacktestRun, { status: "completed" }>;
type Failed = Extract<BacktestRun, { status: "failed" }>;
type Job = { submittedAt: number; end: Completed | Failed };

export function createBacktestMock({ delay = 230, now = Date.now }: { delay?: number; now?: () => number } = {}): BacktestClient {
  const jobs = new Map<string, Job>();
  const history = new Map<string, ReturnType<typeof generateMarketCandles>>();
  let sample: Completed | undefined;
  let sequence = 0;

  function calculate(config: BacktestConfig) {
    const error = validateBacktestConfig(config, range);
    if (error) throw new BacktestInputError(error);
    const strategy = strategies.find(({ id }) => id === config.strategyId);
    const instrument = marketFixture.find(({ id }) => id === config.instrumentId);
    if (!strategy || !instrument) throw new BacktestInputError("Select an available demo strategy and instrument.");
    const candles = history.get(instrument.id) ?? generateMarketCandles(instrument, "1D");
    history.set(instrument.id, candles);
    return replayDemoBacktest(config, candles, strategy.positionSizeBps);
  }

  function runBase(id: string, config: BacktestConfig, offset: number) {
    const at = new Date(baseAt + offset * 60_000).toISOString();
    return { id, config: { ...config }, queuedAt: at, asOf: at, source: "demo", environment: "DEMO" } as const;
  }

  function read(job: Job): BacktestRun {
    const elapsed = now() - job.submittedAt;
    if (elapsed >= 1100) return job.end;
    const { id, config, source, environment, queuedAt } = job.end;
    return { id, config, source, environment, queuedAt, asOf: queuedAt, status: elapsed >= 380 ? "running" : "queued" };
  }

  return {
    async getBacktestWorkspace({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario === "error") throw new Error("Demo workspace unavailable.");
      if (scenario === "denied") return { status: "denied" };
      const runs = Array.from(jobs.values(), read).reverse();
      if (scenario !== "empty") {
        sample ??= { ...runBase("backtest-sample", exampleBacktestConfig, 0), status: "completed", result: calculate(exampleBacktestConfig) };
        runs.push(sample);
      }
      const stale = scenario === "stale";
      return {
        status: stale ? "stale" : "ready",
        data: { ...workspaceBase, asOf: stale ? marketSnapshotDate(true) : runs[0]?.asOf ?? marketSnapshotDate(), runs },
      };
    },

    async startBacktest(config, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario === "stale" || scenario === "denied" || scenario === "error") throw new Error("Demo runs require a current workspace.");
      const result = calculate(config);
      const next = ++sequence;
      const base = runBase(`backtest-${next}`, config, next * 3);
      const asOf = new Date(Date.parse(base.queuedAt) + 60_000).toISOString();
      const end = scenario === "run-error"
        ? { ...base, asOf, status: "failed", message: "The simulated worker could not complete this run." } as const
        : { ...base, asOf, status: "completed", result } as const;
      const job = { submittedAt: now(), end };
      jobs.set(base.id, job);
      return read(job);
    },

    async getBacktestRun(id, { signal } = {}) {
      await waitForMock(signal, delay);
      if (id === sample?.id) return sample;
      const job = jobs.get(id);
      if (!job) throw new Error("Demo run unavailable.");
      return read(job);
    },
  };
}
