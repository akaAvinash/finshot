import { activationBlocker, strategyCandidate, validateStrategyParameters } from "../strategies";
import { waitForMock } from "./mock-delay";
import { createStrategyFixture, unreviewedDraft } from "./strategy-fixture";
import type { Strategy, StrategyClient, StrategyCommand, StrategyParameters } from "./strategy-types";

function makeDraft(parameters: StrategyParameters) {
  const error = validateStrategyParameters(parameters);
  if (error) throw new Error(error);
  return unreviewedDraft({ ...parameters, name: parameters.name.trim(), description: parameters.description.trim() });
}

function updateStrategy(strategy: Strategy, command: Exclude<StrategyCommand, { action: "create" }>, asOf: string): Strategy {
  if (command.action === "save-draft") return { ...strategy, draft: makeDraft(command.parameters) };
  if (command.action === "pause") {
    if (strategy.status !== "active") throw new Error("Only an active demo strategy can be paused.");
    return { ...strategy, status: "paused" };
  }

  if (strategy.status === "active") throw new Error("This demo strategy is already active.");
  const candidate = strategyCandidate(strategy);
  const blocker = activationBlocker(candidate);
  if (blocker) throw new Error(blocker);

  if (!strategy.draft) return { ...strategy, status: "active" };
  return {
    ...strategy,
    status: "active",
    draft: null,
    metrics: null,
    versions: [...strategy.versions, {
      parameters: strategy.draft.parameters,
      backtest: "passed",
      riskReview: "approved",
      number: (strategy.versions.at(-1)?.number ?? 0) + 1,
      activatedAt: asOf,
    }],
  };
}

export function createStrategyMock(delay = 320): StrategyClient {
  let snapshot = createStrategyFixture();
  let nextId = 1;

  return {
    async getStrategies({ scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario === "error") throw new Error("The simulated strategy request failed.");
      if (scenario === "denied" || scenario === "empty") return { status: scenario };
      if (scenario === "stale") return { status: "stale", data: snapshot };
      return { status: "ready", data: snapshot };
    },
    async sendStrategyCommand(command, { scenario = "ready", signal } = {}) {
      await waitForMock(signal, delay);
      if (scenario !== "ready") throw new Error("Strategy actions require current demo data and write access.");

      const asOf = new Date(Date.parse(snapshot.asOf) + 60_000).toISOString();
      if (command.action === "create") {
        const draft = makeDraft(command.parameters);
        const strategy: Strategy = { id: `demo-strategy-${nextId++}`, status: "draft", draft, versions: [], metrics: null };
        snapshot = { ...snapshot, asOf, strategies: [...snapshot.strategies, strategy] };
      } else {
        if (!snapshot.strategies.some(({ id }) => id === command.id)) throw new Error("Demo strategy unavailable.");
        const strategies = snapshot.strategies.map((strategy) => strategy.id === command.id ? updateStrategy(strategy, command, asOf) : strategy);
        snapshot = { ...snapshot, asOf, strategies };
      }

      return snapshot;
    },
  };
}
