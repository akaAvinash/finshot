import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ReportActivity } from "@/components/reports/report-activity";
import { samplePaperReport } from "@/lib/api/paper-report-preview";

vi.mock("@/components/dashboard/portfolio-chart", () => ({ PortfolioChart: () => null }));

it("filters a paginated journal by calendar day and explains when the journal is capped", async () => {
  const user = userEvent.setup();
  const report = samplePaperReport({ from: null, to: null });
  if (report.status !== "ready") throw new Error("Missing example report");
  const { journal, daily } = report.data;
  const extended = [...journal, ...journal.map((row) => ({ ...row, id: `${row.id}-extra` }))];
  render(<ReportActivity days={daily} journal={extended} truncated />);

  expect(screen.getByText(/latest 500 fills/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Next trade page" }));
  expect(screen.getByText("Page 2 of 2")).toBeInTheDocument();
  const day = screen.getByRole("button", { name: /18 Nov 2026, 1 fill/ });
  await user.click(day);
  expect(within(screen.getByRole("table")).getAllByRole("row")).toHaveLength(3);
  expect(within(screen.getByRole("table")).queryByText("RELIANCE")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Clear day" }));
  expect(day).toHaveFocus();
  expect(screen.getByText("Page 1 of 2")).toBeInTheDocument();
});
