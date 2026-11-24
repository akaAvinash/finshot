import { describe, expect, it } from "vitest";
import { createStrategyMock } from "@/lib/api/strategy-mock";
import type { StrategyParameters } from "@/lib/api/strategy-types";
import { activationBlocker } from "@/lib/strategies";

const parameters: StrategyParameters = {
  name: "  Practice range  ", description: "  Sample draft  ", instrument: "NIFTY 50",
  timeframe: "15m", riskTier: "low", positionSizeBps: 501, stopLossBps: 126,
};

describe("strategy demo adapter", () => {
  it("creates a draft with exact inputs and rejects activation without approved checks", async () => {
    const client = createStrategyMock(0);
    const created = await client.sendStrategyCommand({ action: "create", parameters });
    const strategy = created.strategies.at(-1);
    expect(strategy).toMatchObject({
      id: "demo-strategy-1", status: "draft", metrics: null, versions: [],
      draft: { parameters: { ...parameters, name: "Practice range", description: "Sample draft" }, backtest: "unavailable", riskReview: "pending" },
    });
    await expect(client.sendStrategyCommand({ action: "activate", id: "demo-strategy-1" })).rejects.toThrow("passing backtest");
    expect(activationBlocker({ parameters, backtest: "passed", riskReview: "pending" })).toMatch(/approved risk review/);
    await expect(client.getStrategies()).resolves.toEqual({ status: "ready", data: created });
  });

  it("publishes an approved version once, preserves it during edits and clears draft eligibility", async () => {
    const client = createStrategyMock(0);
    const id = "hdfc-reversion";
    const activated = await client.sendStrategyCommand({ action: "activate", id });
    const published = activated.strategies.find((strategy) => strategy.id === id);
    expect(published).toMatchObject({ status: "active", draft: null, versions: [{ number: 1, activatedAt: activated.asOf }] });
    await expect(client.sendStrategyCommand({ action: "activate", id })).rejects.toThrow("already active");
    const paused = await client.sendStrategyCommand({ action: "pause", id });
    expect(paused.strategies.find((strategy) => strategy.id === id)?.status).toBe("paused");
    const resumed = await client.sendStrategyCommand({ action: "activate", id });
    expect(resumed.strategies.find((strategy) => strategy.id === id)?.versions).toEqual(published?.versions);
    await client.sendStrategyCommand({ action: "pause", id });
    const edited = await client.sendStrategyCommand({ action: "save-draft", id, parameters });
    expect(edited.strategies.find((strategy) => strategy.id === id)).toMatchObject({
      status: "paused", versions: published?.versions, draft: { backtest: "unavailable", riskReview: "pending" },
    });
    await expect(client.sendStrategyCommand({ action: "activate", id })).rejects.toThrow("passing backtest");
  });

  it("rejects invalid, stale, denied and cancelled writes without changing its snapshot", async () => {
    const client = createStrategyMock(0);
    const before = await client.getStrategies();
    const command = { action: "create", parameters } as const;
    await expect(client.sendStrategyCommand({ ...command, parameters: { ...parameters, stopLossBps: 100.1 } })).rejects.toThrow("stop loss");
    await expect(client.sendStrategyCommand(command, { scenario: "stale" })).rejects.toThrow("current demo data");
    await expect(client.sendStrategyCommand(command, { scenario: "denied" })).rejects.toThrow("write access");
    const abort = new AbortController();
    const cancelled = client.sendStrategyCommand(command, { signal: abort.signal });
    abort.abort();
    await expect(cancelled).rejects.toHaveProperty("name", "AbortError");
    await expect(client.getStrategies()).resolves.toEqual(before);
  });
});
