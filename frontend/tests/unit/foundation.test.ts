// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createTradeoClient } from "@/lib/api/client";
import { formatInr, formatPercent, formatSnapshotDate } from "@/lib/format";
import { normalizeIndianMobile } from "@/lib/preview-auth/validation";

describe("preview mobile validation", () => {
  it.each(["9876543210", "98765 43210", "+91 98765-43210"])("accepts %s", (value) => {
    expect(normalizeIndianMobile(value)).toBe("9876543210");
  });

  it.each(["", "5876543210", "987654321", "+44 9876543210", "98765a43210"])("rejects %s", (value) => {
    expect(normalizeIndianMobile(value)).toBeNull();
  });
});

describe("market formatting", () => {
  it("formats Indian currency grouping and signed percentages", () => {
    expect(formatInr(124580)).toBe("₹1,24,580.00");
    expect(formatInr(2716, true)).toBe("+₹2,716.00");
    expect(formatInr(-295, true)).toBe("-₹295.00");
    expect(formatPercent(-3.21)).toBe("-3.21%");
    expect(formatPercent(0)).toBe("0.00%");
  });

  it("formats snapshots with the India timezone", () => {
    expect(formatSnapshotDate("2026-11-22T23:30:00Z")).toBe("23 Nov 2026");
  });
});

describe("mock API client", () => {
  it("returns internally consistent ready and older snapshots", async () => {
    vi.useFakeTimers();
    try {
      const readyRequest = createTradeoClient().getDashboard();
      const staleRequest = createTradeoClient({ previewScenario: "stale" }).getDashboard();
      await vi.runAllTimersAsync();

      const [ready, stale] = await Promise.all([readyRequest, staleRequest]);
      expect(ready.status).toBe("ready");
      expect(stale.status).toBe("stale");
      if (ready.status === "empty" || stale.status === "empty") throw new Error("Expected sample snapshots");
      expect(ready.data.portfolio.at(-1)?.value).toBe(ready.data.portfolioValue);
      expect(stale.data.portfolio.at(-1)?.value).toBe(stale.data.portfolioValue);
      expect(Date.parse(stale.data.asOf)).toBeLessThan(Date.parse(ready.data.asOf));
      expect(stale.data.portfolio.length).toBeLessThan(ready.data.portfolio.length);
    } finally {
      vi.useRealTimers();
    }
  });

  it("returns an empty result and surfaces mock failures", async () => {
    const emptyRequest = createTradeoClient({ previewScenario: "empty" }).getDashboard();
    const errorRequest = createTradeoClient({ previewScenario: "error" }).getDashboard();
    await Promise.all([
      expect(emptyRequest).resolves.toEqual({ status: "empty" }),
      expect(errorRequest).rejects.toThrow("Simulated dashboard request failure"),
    ]);
  });

  it("cancels obsolete requests", async () => {
    const controller = new AbortController();
    const response = createTradeoClient().getDashboard({ signal: controller.signal });
    controller.abort();
    await expect(response).rejects.toHaveProperty("name", "AbortError");
    await expect(createTradeoClient().getDashboard({ signal: controller.signal })).rejects.toHaveProperty("name", "AbortError");
  });
});
