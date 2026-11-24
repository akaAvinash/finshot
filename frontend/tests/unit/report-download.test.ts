import { describe, expect, it, vi } from "vitest";
import type { ReportSnapshot } from "@/lib/api/report-types";
import { downloadReportPdf } from "@/lib/report-download";

const pdf = vi.hoisted(() => {
  let page = 1;
  let pages = 1;
  const calls: { page: number; value: string; x: number; y: number }[] = [];
  const doc = {
    setProperties: vi.fn(),
    setFont: vi.fn().mockReturnThis(),
    setFontSize: vi.fn().mockReturnThis(),
    setTextColor: vi.fn().mockReturnThis(),
    setFillColor: vi.fn().mockReturnThis(),
    rect: vi.fn().mockReturnThis(),
    text: vi.fn((value: string, x: number, y: number) => {
      calls.push({ page, value, x, y });
    }),
    addPage: vi.fn(() => { page = ++pages; }),
    getNumberOfPages: vi.fn(() => pages),
    setPage: vi.fn((next: number) => { page = next; return doc; }),
    save: vi.fn(),
  };
  return { doc, calls };
});

vi.mock("jspdf", () => ({
  jsPDF: vi.fn(function () { return pdf.doc; }),
}));

describe("report PDF pagination", () => {
  it("preserves all 24 journal rows, repeats headers and numbers both pages", async () => {
    const snapshot: ReportSnapshot = {
      source: "demo", environment: "DEMO", currency: "INR", period: "7d",
      asOf: "2026-11-23T10:00:00.000Z",
      range: { from: "2026-11-17", to: "2026-11-23" },
      marks: [],
      trades: Array.from({ length: 24 }, (_, i) => ({
        id: `trade-${i + 1}`, symbol: `TEST-${i + 1}`,
        broker: "Zerodha", strategy: "Swing", side: "long", quantity: 1,
        entryPaise: 10000, exitPaise: 10100, brokeragePaise: 5, taxesPaise: 7,
        closedAt: "2026-11-23T06:00:00.000Z",
      })),
    };

    await downloadReportPdf(snapshot, false);

    expect(pdf.doc.addPage).toHaveBeenCalledTimes(1);
    const rows = pdf.calls.filter(({ value }) => value.startsWith("TEST-"));
    expect(rows.map(({ value }) => value)).toEqual(snapshot.trades.map(({ symbol }) => symbol));
    expect(rows.filter(({ page }) => page === 1)).toHaveLength(23);
    expect(rows.filter(({ page }) => page === 2)).toHaveLength(1);
    expect(rows[23]).toMatchObject({ page: 2, y: 52 });

    const headers = ["Close date (IST)", "Symbol", "Broker", "Qty", "Charges", "Net realized"];
    for (const page of [1, 2]) {
      const y = page === 1 ? 108 : 45;
      expect(pdf.calls.filter((call) => call.page === page && call.y === y).map(({ value }) => value)).toEqual(headers);
      expect(pdf.calls.filter((call) => call.page === page && call.value === "Tradeo demo performance report")).toHaveLength(1);
      expect(pdf.calls.filter((call) => call.page === page && call.value.startsWith("DEMO DATA |"))).toEqual([
        { page, value: `DEMO DATA | ${page} / 2`, x: 195, y: 281 },
      ]);
    }
    expect(pdf.calls).toContainEqual({ page: 2, value: "Closed trade journal (continued)", x: 15, y: 37 });
    expect(pdf.doc.save).toHaveBeenCalledWith("tradeo-demo-report-2026-11-17-2026-11-23.pdf");
  });
});
