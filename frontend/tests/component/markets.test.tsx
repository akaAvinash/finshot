import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Markets } from "@/components/markets/markets";
import { Notifications } from "@/components/ui/notifications";
import type { MarketCandle, MarketTimeframe } from "@/lib/api/market-types";

vi.mock("@/components/markets/candlestick-chart", () => ({
  CandlestickChart: ({ candles, timeframe }: { candles: MarketCandle[]; timeframe: MarketTimeframe }) => (
    <div role="group" aria-label={`Demo ${timeframe} candlestick chart`}>{candles.length} bars</div>
  ),
}));

beforeEach(() => {
  const storage = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => storage.get(key) ?? null,
    setItem: (key: string, value: string) => storage.set(key, value),
  });
});

afterEach(() => vi.unstubAllGlobals());

describe("Markets", () => {
  it("searches the catalog, selects an instrument and switches chart timeframes", async () => {
    const user = userEvent.setup();
    render(<Markets />);
    expect(screen.getByRole("status", { name: "Loading market overview" })).toBeInTheDocument();
    const find = screen.getByRole("button", { name: "Find instrument" });
    await screen.findByRole("heading", { name: "Market overview" });

    await user.click(find);
    const dialog = screen.getByRole("dialog", { name: "Find an instrument" });
    const input = within(dialog).getByRole("searchbox", { name: "Search instruments" });
    await user.type(input, "never listed");
    expect(within(dialog).getByText("No instruments match your search.")).toBeInTheDocument();
    await user.clear(input);
    await user.type(input, "nifty bank");
    await user.click(within(dialog).getByRole("button", { name: "Select BANKNIFTY" }));

    expect(screen.getByRole("heading", { name: "BANKNIFTY" })).toBeInTheDocument();
    expect(find).toHaveFocus();
    const timeframes = screen.getByRole("group", { name: "Chart timeframe" });
    const daily = within(timeframes).getByRole("button", { name: "1D" });
    await user.click(daily);
    expect(daily).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("status", { name: "Loading chart" })).toBeInTheDocument();
    expect(await screen.findByRole("group", { name: "Demo 1D candlestick chart" })).toHaveTextContent("38 bars");
  });

  it("adds, filters, selects, removes and persists watchlist instruments", async () => {
    const user = userEvent.setup();
    const view = render(<Notifications><Markets /></Notifications>);
    const add = await screen.findByRole("button", { name: "Add instrument" });
    await user.click(add);
    const dialog = screen.getByRole("dialog", { name: "Find an instrument" });
    await user.type(within(dialog).getByRole("searchbox"), "finnifty");
    await user.click(within(dialog).getByRole("button", { name: "Add FINNIFTY to watchlist" }));
    await user.keyboard("{Escape}");

    const watchlist = screen.getByRole("region", { name: /^Watchlist/ });
    const search = within(watchlist).getByRole("searchbox");
    await user.type(search, "not saved");
    expect(within(watchlist).getByText("No saved instruments match your search.")).toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "fin");
    await user.click(within(watchlist).getByRole("button", { name: "View FINNIFTY from watchlist" }));
    expect(screen.getByRole("heading", { name: "FINNIFTY" })).toBeInTheDocument();

    view.unmount();
    render(<Markets />);
    const saved = await screen.findByRole("button", { name: "View FINNIFTY from watchlist" });
    expect(saved).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove FINNIFTY from watchlist" }));
    expect(saved).not.toBeInTheDocument();
  });

  it("renders a stale chart and recovers from empty and failed requests", async () => {
    const user = userEvent.setup();
    render(<Markets />);
    await screen.findByRole("group", { name: "Demo 15m candlestick chart" });

    async function choose(name: string) {
      await user.click(screen.getByRole("button", { name: "Chart demo data" }));
      const dialog = screen.getByRole("dialog", { name: "Chart demo data" });
      await user.click(within(dialog).getByRole("radio", { name }));
      await user.click(within(dialog).getByRole("button", { name: "Apply chart response" }));
    }

    await choose("Stale candles");
    expect(await screen.findByText("Showing stale demo candles.")).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Demo 15m candlestick chart" })).toBeInTheDocument();

    await choose("Empty chart");
    expect(await screen.findByText("No candles available")).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Demo 15m candlestick chart" })).not.toBeInTheDocument();

    await choose("Request error");
    expect(await screen.findByRole("alert")).toHaveTextContent("Chart could not load");
    await user.click(screen.getByRole("button", { name: "Retry chart" }));
    expect(await screen.findByRole("group", { name: "Demo 15m candlestick chart" })).toBeInTheDocument();
  });
});
