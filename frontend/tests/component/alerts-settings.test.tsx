import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Alerts } from "@/components/alerts/alerts";
import { Settings } from "@/components/settings/settings";
import { WorkspaceControlsProvider } from "@/components/workspace-controls-provider";

describe("Alerts and Settings", () => {
  it("filters and acknowledges inbox alerts and recovers from preview states", async () => {
    const user = userEvent.setup();
    render(<WorkspaceControlsProvider><Alerts /></WorkspaceControlsProvider>);
    expect(screen.getByRole("status", { name: "Loading alerts" })).toBeInTheDocument();
    const inbox = await screen.findByRole("region", { name: "Alert inbox" });
    await user.click(within(inbox).getByRole("button", { name: "Unread" }));
    await user.selectOptions(within(inbox).getByRole("combobox", { name: "Filter alerts by source" }), "risk");
    expect(within(inbox).getByRole("heading", { name: "Paper risk limit reached" })).toBeInTheDocument();
    expect(within(inbox).queryByRole("heading", { name: "Paper order rejected" })).not.toBeInTheDocument();
    await user.click(within(inbox).getByRole("button", { name: "Acknowledge Paper risk limit reached" }));
    expect(await within(inbox).findByText("No alerts match this view.")).toBeInTheDocument();

    const scenarios = screen.getByRole("combobox", { name: "Alerts preview data" });
    await user.selectOptions(scenarios, "stale");
    expect(await screen.findByText("The inbox is stale. Acknowledgement is paused.")).toBeInTheDocument();
    await user.selectOptions(scenarios, "empty");
    expect(await screen.findByRole("heading", { name: "No alerts yet" })).toBeInTheDocument();
    await user.selectOptions(scenarios, "denied");
    expect(await screen.findByRole("heading", { name: "Alerts access denied" })).toBeInTheDocument();
    await user.selectOptions(scenarios, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Alerts could not load");
    await user.click(screen.getByRole("button", { name: "Retry alerts" }));
    expect(await screen.findByRole("region", { name: "Alert inbox" })).toBeInTheDocument();
  });

  it("focuses the inbox when a pending acknowledgement becomes hidden by the unread filter", async () => {
    render(<WorkspaceControlsProvider><Alerts /></WorkspaceControlsProvider>);
    const acknowledge = await screen.findByRole("button", { name: "Acknowledge Paper risk limit reached" });
    fireEvent.click(acknowledge);
    expect(acknowledge).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Unread" }));
    expect(screen.getByRole("heading", { name: "Paper risk limit reached" })).toBeInTheDocument();

    await waitFor(() => expect(screen.queryByRole("heading", { name: "Paper risk limit reached" })).not.toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Alert inbox" })).toHaveFocus();
  });

  it("restores keyboard focus when a profile save succeeds or fails", async () => {
    const user = userEvent.setup();
    render(<WorkspaceControlsProvider><Settings /></WorkspaceControlsProvider>);
    const originalName = await screen.findByRole("textbox", { name: "Demo display name" });
    await user.clear(originalName);
    await user.type(originalName, " Paper Trader {Enter}");
    await waitFor(() => expect(screen.getByRole("list", { name: "Demo settings audit trail" })).toHaveTextContent("Profile preferences updated"));

    const savedName = screen.getByRole("textbox", { name: "Demo display name" });
    expect(savedName).toHaveValue("Paper Trader");
    expect(savedName).toHaveFocus();
    await user.clear(savedName);
    await user.type(savedName, " {Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a display name");
    expect(savedName).toHaveFocus();
  });

  it("confirms a sample phone change and makes stale settings read-only", async () => {
    const user = userEvent.setup();
    render(<WorkspaceControlsProvider><Settings /></WorkspaceControlsProvider>);
    expect(screen.getByRole("status", { name: "Loading settings" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Verify sample phone" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm sample phone" });
    const code = within(dialog).getByRole("textbox", { name: "Demo verification code" });
    await user.type(code, "000000");
    await user.click(within(dialog).getByRole("button", { name: "Confirm demo change" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("Enter the sample verification code");
    await user.clear(code);
    await user.type(code, "246810");
    await user.click(within(dialog).getByRole("button", { name: "Confirm demo change" }));
    expect(await screen.findByText("Demo verified")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Demo settings audit trail" })).toHaveTextContent("Sample phone verified");

    const scenarios = screen.getByRole("combobox", { name: "Settings preview data" });
    await user.selectOptions(scenarios, "stale");
    expect(await screen.findByText("Settings are stale. Demo account changes are paused.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save profile" })).toBeDisabled();
    await user.selectOptions(scenarios, "empty");
    expect(await screen.findByRole("heading", { name: "No settings to display" })).toBeInTheDocument();
    await user.selectOptions(scenarios, "denied");
    expect(await screen.findByRole("heading", { name: "Settings access denied" })).toBeInTheDocument();
    await user.selectOptions(scenarios, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Settings could not load");
    await user.click(screen.getByRole("button", { name: "Retry settings" }));
    expect(await screen.findByText("Demo verified")).toBeInTheDocument();
  });
});
