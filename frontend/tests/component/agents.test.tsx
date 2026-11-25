import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Agents } from "@/components/agents/agents";

describe("Agents", () => {
  it("filters the timeline, pauses observers, and records advisory review", async () => {
    const user = userEvent.setup();
    render(<Agents />);
    expect(screen.getByRole("status", { name: "Loading agents" })).toBeInTheDocument();
    const scanner = await screen.findByRole("region", { name: "Market Scanner" });
    const timeline = screen.getByRole("region", { name: "Advisory timeline" });
    await user.selectOptions(within(timeline).getByRole("combobox", { name: "Filter events by severity" }), "critical");
    expect(within(timeline).getByRole("heading", { name: "Risk limit applied" })).toBeInTheDocument();
    expect(within(timeline).queryByRole("heading", { name: "Signal proposed" })).not.toBeInTheDocument();
    await user.selectOptions(within(timeline).getByRole("combobox", { name: "Filter events by severity" }), "all");

    await user.click(within(scanner).getByRole("button", { name: "Pause Market Scanner" }));
    expect(await within(scanner).findByText("Paused", { exact: true })).toBeInTheDocument();
    expect(within(timeline).getByRole("heading", { name: "Observer paused" })).toBeInTheDocument();
    await user.click(within(scanner).getByRole("button", { name: "Resume Market Scanner" }));
    expect(await within(scanner).findByText("Healthy", { exact: true })).toBeInTheDocument();

    await user.click(within(timeline).getByRole("button", { name: "Review Signal proposed" }));
    const dialog = screen.getByRole("dialog", { name: "Review signal proposed" });
    expect(dialog).toHaveTextContent("Neither action authorizes an order or changes a risk limit.");
    await user.click(within(dialog).getByRole("button", { name: "Acknowledge" }));
    const item = (await within(timeline).findByRole("heading", { name: "Signal proposed" })).closest("li");
    if (!item) throw new Error("Expected a timeline item.");
    expect(await within(item).findByText("Acknowledged", { exact: true })).toBeInTheDocument();
  });

  it("shows stale, empty, denied and failed responses and recovers", async () => {
    const user = userEvent.setup();
    render(<Agents />);
    await screen.findByRole("region", { name: "Market Scanner" });
    const data = screen.getByRole("combobox", { name: "Agent preview data" });
    await user.selectOptions(data, "stale");
    expect(await screen.findByText("Agent telemetry is stale. Advisory controls are paused.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pause Market Scanner" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Review Telemetry unavailable" })).toBeDisabled();
    await user.selectOptions(data, "empty");
    expect(await screen.findByRole("heading", { name: "No agent activity" })).toBeInTheDocument();
    await user.selectOptions(data, "denied");
    expect(await screen.findByRole("heading", { name: "Agent access denied" })).toBeInTheDocument();
    await user.selectOptions(data, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Agents could not load");
    await user.click(screen.getByRole("button", { name: "Retry agent data" }));
    expect(await screen.findByRole("region", { name: "Market Scanner" })).toBeInTheDocument();
  });
});
