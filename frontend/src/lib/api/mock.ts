import { dashboardFixture } from "./dashboard-fixture";
import type { TradeoClient } from "./types";

export const previewScenarios = [
  { value: "ready", label: "Sample data" },
  { value: "stale", label: "Stale data" },
  { value: "empty", label: "Empty dashboard" },
  { value: "error", label: "Request error" },
] as const;

export type PreviewScenario = (typeof previewScenarios)[number]["value"];

function waitForMock(signal?: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason);
      return;
    }

    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, 420);

    function onAbort() {
      clearTimeout(timer);
      reject(signal?.reason);
    }

    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export function createMockClient(scenario: PreviewScenario = "ready"): TradeoClient {
  return {
    async getDashboard({ signal } = {}) {
      await waitForMock(signal);

      if (scenario === "error") throw new Error("Simulated dashboard request failure");
      if (scenario === "empty") return { status: "empty" };

      const data = structuredClone(dashboardFixture);
      if (scenario === "stale") {
        data.asOf = "2026-11-20T15:30:00+05:30";
        data.portfolio = data.portfolio.slice(0, -1);
        data.portfolioValue = 121864;
        data.dayPnl = -546;
        data.dayReturn = -0.45;
        data.monthPnl = 6434;
        data.monthReturn = 5.57;
        data.recentTrades = [];
      }

      return { status: scenario, data };
    },
  };
}
