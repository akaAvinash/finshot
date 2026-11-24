import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { Strategies } from "@/components/strategies/strategies";

describe("Strategies", () => {
  it("filters and switches views, creates a draft, and prevents unchecked activation", async () => {
    const user = userEvent.setup();
    render(<Strategies />);
    expect(screen.getByRole("status", { name: "Loading strategies" })).toBeInTheDocument();
    const momentum = await screen.findByRole("region", { name: "NIFTY Momentum" });
    expect(within(momentum).getByText("+₹7,420.25")).toBeInTheDocument();

    await user.selectOptions(screen.getByRole("combobox", { name: "Filter strategies by risk" }), "high");
    expect(screen.queryByRole("region", { name: "NIFTY Momentum" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Table view" }));
    expect(within(screen.getByRole("table", { name: "Demo strategies" })).getByRole("rowheader", { name: "FinNifty Breakout" })).toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search strategies" }), "unknown");
    expect(screen.getByRole("heading", { name: "No strategies match" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create strategy" }));
    const editor = screen.getByRole("dialog", { name: "Create strategy draft" });
    await user.type(within(editor).getByLabelText("Strategy name"), "Practice range");
    await user.click(within(editor).getByRole("button", { name: "Save draft" }));
    await user.click(await screen.findByRole("button", { name: "View Practice range" }));
    const draft = screen.getByRole("dialog", { name: "Practice range" });
    expect(within(draft).getByText("No deployed versions yet.")).toBeInTheDocument();
    expect(within(draft).getByRole("button", { name: "Activate demo" })).toBeDisabled();
  });

  it("shows stale, empty, denied and failed responses and can recover", async () => {
    const user = userEvent.setup();
    render(<Strategies />);
    await screen.findByRole("region", { name: "NIFTY Momentum" });
    const response = screen.getByRole("combobox", { name: "Strategy preview data" });

    await user.selectOptions(response, "stale");
    expect(await screen.findByText("Strategy data is stale. Editing and activation are paused.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create strategy" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "View NIFTY Momentum" }));
    expect(screen.getByRole("button", { name: "Edit draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Pause demo" })).toBeDisabled();
    await user.keyboard("{Escape}");

    await user.selectOptions(response, "empty");
    expect(await screen.findByRole("heading", { name: "No strategies to display" })).toBeInTheDocument();
    await user.selectOptions(response, "denied");
    expect(await screen.findByRole("heading", { name: "Strategy access denied" })).toBeInTheDocument();
    await user.selectOptions(response, "error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Strategies could not load");
    await user.click(screen.getByRole("button", { name: "Retry strategy data" }));
    expect(await screen.findByRole("region", { name: "NIFTY Momentum" })).toBeInTheDocument();
  });
});
