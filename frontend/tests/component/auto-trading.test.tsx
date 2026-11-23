import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { AutoTrading } from "@/components/auto-trading/auto-trading";

describe("Auto Trading preview", () => {
  it("assigns and starts a strategy, then requires a typed stop confirmation", async () => {
    const user = userEvent.setup();
    render(<AutoTrading />);
    expect(screen.getByRole("status", { name: "Loading paper workspace" })).toBeInTheDocument();

    await screen.findByRole("heading", { name: "Paper engine" });
    expect(screen.getByText("Live trading unavailable")).toBeInTheDocument();
    const strategy = screen.getByRole("combobox", { name: "Assigned strategy" });
    await user.selectOptions(strategy, "bank-range");
    await user.click(screen.getByRole("tab", { name: "Event log" }));
    expect(await screen.findByText("Assigned Bank Nifty Range.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Start paper engine" }));
    await screen.findByRole("button", { name: "Pause paper engine" });
    expect(strategy).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Paper kill switch" }));
    const dialog = screen.getByRole("dialog", { name: "Halt paper trading?" });
    const confirm = within(dialog).getByRole("button", { name: "Confirm paper halt" });
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByRole("textbox", { name: "Type STOP to confirm" }), "STOP");
    await user.click(confirm);
    await screen.findByRole("button", { name: "Clear paper halt" });
    expect(await screen.findByText(/Cancelled 2 pending paper orders/)).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Order queue" }));
    expect(screen.getAllByText("Cancelled", { exact: true })).toHaveLength(2);
    await user.click(screen.getByRole("tab", { name: "Trade log" }));
    expect(screen.getByRole("rowheader", { name: "HDFCBANK" })).toBeInTheDocument();
  });

  it("blocks stale controls and recovers from empty, denied and error states", async () => {
    const user = userEvent.setup();
    render(<AutoTrading />);
    await screen.findByRole("heading", { name: "Paper engine" });
    const response = screen.getByRole("combobox", { name: "Paper preview data" });

    await user.selectOptions(response, "stale");
    expect(await screen.findByText("Paper data is stale. Controls are paused.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start paper engine" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Paper kill switch" })).toBeDisabled();

    await user.selectOptions(response, "empty");
    expect(await screen.findByRole("heading", { name: "No paper activity" })).toBeInTheDocument();

    await user.selectOptions(response, "denied");
    expect(await screen.findByRole("heading", { name: "Paper workspace access denied" })).toBeInTheDocument();

    await user.selectOptions(response, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Paper workspace could not load");

    await user.click(screen.getByRole("button", { name: "Retry paper data" }));
    expect(await screen.findByRole("button", { name: "Start paper engine" })).toBeEnabled();
  });
});
