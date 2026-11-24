import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Backtesting } from "@/components/backtesting/backtesting";
import * as apiClient from "@/lib/api/client";

vi.mock("@/components/dashboard/portfolio-chart", () => ({
  PortfolioChart: ({ label }: { label: string }) => <div role="group" aria-label={label} />,
}));

describe("Backtesting", () => {
  it("validates the holdout, queues a first run, and shows completed results", async () => {
    const user = userEvent.setup();
    render(<Backtesting />);
    expect(screen.getByRole("status", { name: "Loading backtests" })).toBeInTheDocument();
    await screen.findByRole("heading", { name: "Demo backtest results" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Backtest preview data" }), "empty");
    await screen.findByRole("heading", { name: "No backtest results yet" });
    const holdout = screen.getByLabelText("Out-of-sample start");
    await user.clear(holdout);
    await user.type(holdout, "2026-10-05");
    await user.click(screen.getByRole("button", { name: "Run demo backtest" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("must fall between");

    await user.clear(holdout);
    await user.type(holdout, "2026-10-21");
    await user.click(screen.getByRole("button", { name: "Run demo backtest" }));
    const queue = screen.getByRole("region", { name: "Run queue" });
    expect(await within(queue).findByText("Queued")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Demo backtest results" }, { timeout: 3000 })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Drawdown" }));
    expect(screen.getByRole("group", { name: "Demo drawdown chart" })).toBeInTheDocument();
  });

  it("handles stale, denied, failed workspace and failed run responses", async () => {
    const user = userEvent.setup();
    render(<Backtesting />);
    await screen.findByRole("heading", { name: "Demo backtest results" });
    const scenario = screen.getByRole("combobox", { name: "Backtest preview data" });
    await user.selectOptions(scenario, "stale");
    expect(await screen.findByText("Backtest data is stale. New runs are paused.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run demo backtest" })).toBeDisabled();
    await user.selectOptions(scenario, "denied");
    expect(await screen.findByRole("heading", { name: "Backtest access denied" })).toBeInTheDocument();
    await user.selectOptions(scenario, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Backtesting could not load");
    await user.selectOptions(scenario, "run-error");
    await user.click(await screen.findByRole("button", { name: "Run demo backtest" }));
    expect(await screen.findByRole("heading", { name: "Demo backtest failed" }, { timeout: 3000 })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run demo backtest" })).toBeEnabled();
  });

  it("resumes polling after a status request fails and unlocks the controls", async () => {
    const user = userEvent.setup();
    const client = apiClient.createTradeoClient();
    const workspace = await client.getBacktestWorkspace();
    if (workspace.status !== "ready") throw new Error("Expected a ready demo workspace.");
    const sample = workspace.data.runs[0];
    if (sample?.status !== "completed") throw new Error("Expected a completed demo run.");

    vi.spyOn(client, "getBacktestWorkspace").mockResolvedValue({
      status: "ready", data: { ...workspace.data, runs: [] },
    });
    const poll = vi.spyOn(client, "getBacktestRun")
      .mockRejectedValueOnce(new Error("Status unavailable"))
      .mockResolvedValueOnce({ ...sample, id: "backtest-1" });
    const factory = vi.spyOn(apiClient, "createTradeoClient").mockReturnValue(client);

    try {
      render(<Backtesting />);
      await user.click(await screen.findByRole("button", { name: "Run demo backtest" }));
      expect(await screen.findByRole("alert")).toHaveTextContent("Run status could not refresh.");
      expect(screen.getByRole("button", { name: "Demo run in progress" })).toBeDisabled();
      expect(screen.getByRole("combobox", { name: "Backtest preview data" })).toBeDisabled();

      await user.click(screen.getByRole("button", { name: "Retry run status" }));
      expect(await screen.findByRole("heading", { name: "Demo backtest results" })).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Run demo backtest" })).toBeEnabled();
      expect(screen.getByRole("combobox", { name: "Backtest preview data" })).toBeEnabled();
      expect(poll).toHaveBeenCalledTimes(2);
    } finally {
      factory.mockRestore();
    }
  });
});
