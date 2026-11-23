import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Dashboard } from "@/components/dashboard/dashboard";
import { Notifications } from "@/components/ui/notifications";

vi.mock("@/components/dashboard/portfolio-chart", () => ({
  PortfolioChart: () => <div data-testid="portfolio-plot" />,
}));

async function selectScenario(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(screen.getByRole("button", { name: "Preview data" }));
  const dialog = screen.getByRole("dialog", { name: "Preview data" });
  await user.click(within(dialog).getByRole("radio", { name }));
  await user.click(within(dialog).getByRole("button", { name: "Apply preview" }));
}

describe("Dashboard", () => {
  it("loads sample data, changes the chart period, and announces refresh", async () => {
    const user = userEvent.setup();
    render(<Notifications><Dashboard /></Notifications>);
    expect(screen.getByRole("status", { name: "Loading dashboard" })).toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Watchlist" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    const week = screen.getByRole("button", { name: "1W" });
    await user.click(week);
    expect(week).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("over one week")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Refresh sample data" }));
    expect(await screen.findByText("Sample data refreshed")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Dismiss notification" }));
    expect(screen.queryByText("Sample data refreshed")).not.toBeInTheDocument();
  });

  it("shows stale and empty data and recovers from a simulated request error", async () => {
    const user = userEvent.setup();
    render(<Dashboard />);
    await selectScenario(user, "Stale data");
    expect(await screen.findByText("Showing an older sample snapshot.")).toBeInTheDocument();
    expect(screen.getByText("No trades are available in this sample snapshot.")).toBeInTheDocument();

    await selectScenario(user, "Empty dashboard");
    expect(await screen.findByRole("heading", { name: "No sample data" })).toBeInTheDocument();

    await selectScenario(user, "Request error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Sample data could not load");
    await user.click(screen.getByRole("button", { name: "Retry with sample data" }));
    expect(await screen.findByRole("heading", { name: "Recent trades" })).toBeInTheDocument();
  });
});
