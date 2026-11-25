import { describe, expect, it } from "vitest";
import { createAgentsMock } from "@/lib/api/agent-mock";

describe("Agents preview adapter", () => {
  it("pauses and resumes an observer while preserving its telemetry and ordering events", async () => {
    const client = createAgentsMock(0);
    const initial = await client.getAgents();
    if (initial.status !== "ready") throw new Error("Expected a ready demo snapshot.");
    const first = initial.data.agents.find(({ id }) => id === "risk");
    const paused = await client.sendAgentCommand({ kind: "pause", agentId: "risk" });
    const resumed = await client.sendAgentCommand({ kind: "resume", agentId: "risk" });
    expect(paused.agents.find(({ id }) => id === "risk")).toEqual({ ...first, paused: true });
    expect(paused.events[0]).toMatchObject({ reason: "OBSERVER_PAUSED", at: paused.asOf });
    expect(resumed.agents.find(({ id }) => id === "risk")).toEqual(first);
    expect(resumed.events.slice(0, 2).map(({ reason }) => reason)).toEqual(["OBSERVER_RESUMED", "OBSERVER_PAUSED"]);
  });

  it("records an advisory acknowledgement without changing telemetry or other items", async () => {
    const client = createAgentsMock(0);
    const initial = await client.getAgents();
    if (initial.status !== "ready") throw new Error("Expected a ready demo snapshot.");
    const updates = await Promise.allSettled([
      client.sendAgentCommand({ kind: "acknowledge", eventId: "event-4" }),
      client.sendAgentCommand({ kind: "dismiss", eventId: "event-4" }),
    ]);
    const successes = updates.filter((update) => update.status === "fulfilled");
    expect(successes).toHaveLength(1);
    expect(successes[0].value.agents).toEqual(initial.data.agents);
    expect(successes[0].value.events.find(({ id }) => id === "event-4")?.review).toBe("acknowledged");
    expect(successes[0].value.events.find(({ id }) => id === "event-3")?.review).toBe("pending");
    expect(updates[1]).toMatchObject({ status: "rejected" });
  });

  it("excludes events newer than a stale snapshot and rejects stale or denied changes", async () => {
    const client = createAgentsMock(0);
    const stale = await client.getAgents({ scenario: "stale" });
    if (stale.status !== "stale") throw new Error("Expected stale telemetry.");
    expect(stale.data.events.every(({ at }) => at <= stale.data.asOf)).toBe(true);
    expect(stale.data.agents.find(({ id }) => id === "strategy")).toMatchObject({ lastSeenAt: null, latencyMs: null, failureCount: null });
    const command = { kind: "pause", agentId: "scanner" } as const;
    await expect(client.sendAgentCommand(command, { scenario: "stale" })).rejects.toThrow(/current demo data/);
    await expect(client.sendAgentCommand(command, { scenario: "denied" })).rejects.toThrow(/current demo data/);
    await expect(client.getAgents()).resolves.toMatchObject({ status: "ready", data: { agents: [{ id: "scanner", paused: false }, expect.anything(), expect.anything(), expect.anything()] } });
  });
});
