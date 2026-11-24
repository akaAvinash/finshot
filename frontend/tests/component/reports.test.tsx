import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Reports } from "@/components/reports/reports";

vi.mock("@/components/dashboard/portfolio-chart", () => ({
  PortfolioChart: ({ label }: { label: string }) => <div role="group" aria-label={label} />,
}));

describe("Reports", () => {
  it("changes the period and filters the closed trade journal by day and outcome", async () => {
    const user = userEvent.setup();
    render(<Reports />);
    expect(screen.getByRole("status", { name: "Loading reports" })).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Trade journal" });
    await user.click(screen.getByRole("button", { name: "7 days" }));
    expect(await screen.findByText("17 Nov 2026 to 23 Nov 2026 IST")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous report month" })).toBeDisabled();
    const calendar = screen.getByRole("region", { name: "Daily P&L" });
    await user.click(within(calendar).getByRole("button", { name: /23 Nov 2026, 2 closed trades/ }));
    const journal = screen.getByRole("region", { name: "Trade journal" });
    expect(within(journal).getByText(/2 closed trades · 23 Nov 2026/)).toBeInTheDocument();

    await user.selectOptions(within(journal).getByRole("combobox", { name: "Filter trades by outcome" }), "loss");
    expect(within(journal).queryByText(/2 closed trades · 23 Nov 2026/)).not.toBeInTheDocument();
    await user.click(within(calendar).getByRole("button", { name: "Clear day" }));
    expect(within(screen.getByRole("region", { name: "Trade journal" })).getByText(/Selected period/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "90 days" }));
    const previous = await screen.findByRole("button", { name: "Previous report month" });
    await user.click(previous);
    expect(screen.getByText("October 2026")).toBeInTheDocument();
  });

  it("displays stale, permission, empty and failed data and can recover", async () => {
    const user = userEvent.setup();
    render(<Reports />);
    await screen.findByRole("heading", { name: "Trade journal" });
    const scenario = screen.getByRole("combobox", { name: "Report preview data" });
    await user.selectOptions(scenario, "stale");
    expect(await screen.findByText(/Report data is stale/)).toBeInTheDocument();
    expect(screen.getAllByText("Unavailable", { exact: true })).toHaveLength(2);
    await user.selectOptions(scenario, "empty");
    expect(await screen.findByRole("heading", { name: "No report data" })).toBeInTheDocument();
    await user.selectOptions(scenario, "denied");
    expect(await screen.findByRole("heading", { name: "Report access denied" })).toBeInTheDocument();
    await user.selectOptions(scenario, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Reports could not load");
    await user.click(screen.getByRole("button", { name: "Retry report data" }));
    expect(await screen.findByRole("heading", { name: "Trade journal" })).toBeInTheDocument();
  });
});
