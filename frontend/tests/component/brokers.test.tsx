import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Brokers } from "@/components/brokers/brokers";
import { Notifications } from "@/components/ui/notifications";

describe("Brokers", () => {
  it("filters providers and reconnects, syncs and disconnects a demo account", async () => {
    const user = userEvent.setup();
    render(<Notifications><Brokers /></Notifications>);
    expect(screen.getByRole("status", { name: "Loading brokers" })).toBeInTheDocument();
    const fyers = await screen.findByRole("region", { name: "Fyers" });
    expect(within(fyers).getByText("Session expired")).toBeInTheDocument();
    expect(within(fyers).getByText("•••• 0956")).toBeInTheDocument();
    const filter = screen.getByRole("combobox", { name: "Filter broker connections" });
    await user.selectOptions(filter, "expired");
    expect(screen.queryByRole("region", { name: "Zerodha" })).not.toBeInTheDocument();

    await user.click(within(fyers).getByRole("button", { name: "Reconnect demo" }));
    const reconnect = screen.getByRole("dialog", { name: "Reconnect Fyers demo?" });
    await user.click(within(reconnect).getByRole("button", { name: "Reconnect demo account" }));
    expect(await within(fyers).findByRole("button", { name: "Sync demo account" })).toBeInTheDocument();
    expect(filter).toHaveValue("all");
    expect(within(fyers).getByText("Not synced")).toBeInTheDocument();

    await user.click(within(fyers).getByRole("button", { name: "Sync demo account" }));
    expect(await screen.findByText("Fyers demo account synced")).toBeInTheDocument();
    expect(within(fyers).queryByText("Not synced")).not.toBeInTheDocument();

    await user.click(within(fyers).getByRole("button", { name: "Disconnect" }));
    const disconnect = screen.getByRole("dialog", { name: "Disconnect Fyers demo?" });
    await user.click(within(disconnect).getByRole("button", { name: "Disconnect demo account" }));
    expect(await within(fyers).findByRole("button", { name: "Connect demo" })).toBeInTheDocument();
    expect(within(fyers).queryByText("•••• 0956")).not.toBeInTheDocument();
    expect(screen.getByText("Account disconnected")).toBeInTheDocument();
  });

  it("covers empty filters and stale, empty, denied and failed responses", async () => {
    const user = userEvent.setup();
    render(<Brokers />);
    await screen.findByRole("region", { name: "Zerodha" });
    await user.selectOptions(screen.getByRole("combobox", { name: "Filter broker connections" }), "disconnected");
    expect(screen.getByRole("heading", { name: "No brokers match this filter" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show all brokers" }));
    const response = screen.getByRole("combobox", { name: "Broker preview data" });

    await user.selectOptions(response, "stale");
    expect(await screen.findByText("Broker data is stale. Account actions are paused.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect demo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Sync demo account" })).toBeDisabled();

    await user.selectOptions(response, "empty");
    expect(await screen.findByRole("heading", { name: "No broker connections to display" })).toBeInTheDocument();
    await user.selectOptions(response, "denied");
    expect(await screen.findByRole("heading", { name: "Broker access denied" })).toBeInTheDocument();
    await user.selectOptions(response, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Brokers could not load");
    await user.click(screen.getByRole("button", { name: "Retry broker data" }));
    expect(await screen.findByRole("button", { name: "Reconnect demo" })).toBeEnabled();
  });
});
