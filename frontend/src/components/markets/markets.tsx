"use client";

import { useRef, useState, type MouseEvent } from "react";
import { Search } from "lucide-react";
import { DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useNotification } from "@/components/ui/notifications";
import { Status } from "@/components/ui/status";
import type { Instrument, MarketTimeframe } from "@/lib/api/market-types";
import type { MarketMode } from "@/lib/api/market-client";
import type { MarketChartScenario } from "@/lib/api/market-mock";
import { updateWatchlist, useWatchlist } from "@/lib/market/watchlist";
import { InstrumentSearch } from "./instrument-search";
import { MarketChartPanel } from "./market-chart-panel";
import { MarketPreviewControls } from "./market-preview-controls";
import { InstrumentDetails, MarketOverviewCards, MarketSession } from "./market-summary";
import { MarketWatchlist } from "./market-watchlist";
import { useMarketSnapshot, type ChartRequest } from "./use-market-data";

const overviewIds = ["NSE:NIFTY50", "NSE:BANKNIFTY", "NSE:FINNIFTY", "NSE:RELIANCE"];
const defaultRequest: ChartRequest = { instrumentId: overviewIds[0], timeframe: "15m", scenario: "ready" };

export function Markets({ mode = "preview" }: { mode?: MarketMode }) {
  const { snapshot, retry } = useMarketSnapshot(mode);
  const [request, setRequest] = useState(defaultRequest);
  const [searchOpen, setSearchOpen] = useState(false);
  const searchOpener = useRef<HTMLButtonElement | null>(null);
  const watchlist = useWatchlist();
  const notify = useNotification();

  function openSearch(event: MouseEvent<HTMLButtonElement>) {
    searchOpener.current = event.currentTarget;
    setSearchOpen(true);
  }

  function selectInstrument(instrumentId: string) {
    setRequest((current) => current.instrumentId === instrumentId ? current : { ...current, instrumentId });
  }

  function selectTimeframe(timeframe: MarketTimeframe) {
    setRequest((current) => current.timeframe === timeframe ? current : { ...current, timeframe });
  }

  function selectScenario(scenario: MarketChartScenario) {
    setRequest((current) => ({ ...current, scenario }));
  }

  function toggleWatchlist(instrument: Instrument, add: boolean) {
    updateWatchlist(instrument.id, add);
    notify(`${instrument.symbol} ${add ? "added to" : "removed from"} watchlist`);
  }

  const instruments = snapshot.status === "ready" ? snapshot.data.instruments : [];
  const quotes = new Map(snapshot.status === "ready" ? snapshot.data.overview.quotes.map((quote) => [quote.instrumentId, quote]) : []);
  const instrument = instruments.find(({ id }) => id === request.instrumentId) ?? instruments.find(({ id }) => quotes.has(id));
  const activeId = instrument?.id ?? request.instrumentId;
  const selectedQuote = quotes.get(activeId);
  const overviewItems = (overviewIds.some((id) => quotes.has(id)) ? overviewIds : instruments.filter(({ id }) => quotes.has(id)).slice(0, 4).map(({ id }) => id)).flatMap((id) => {
    const item = instruments.find((candidate) => candidate.id === id);
    const quote = quotes.get(id);
    return item && quote ? [{ instrument: item, quote }] : [];
  });

  return (
    <div className="space-y-4 sm:space-y-5">
      <PageHeading title="Markets" description="Explore NSE instruments, price action and your watchlist." actions={
        <>
          <Status tone="accent" dot>{mode === "preview" ? "Demo data" : snapshot.status === "ready" && snapshot.data.overview.source === "demo" ? "Backend demo data" : "Market API"}</Status>
          <Button variant="outline" onClick={openSearch} disabled={!instruments.length}>
            <Search aria-hidden /> Find instrument
          </Button>
          {mode === "preview" && <MarketPreviewControls scenario={request.scenario} onApply={selectScenario} />}
        </>
      } />
      {snapshot.status === "loading" && (
        <Card role="status" aria-label="Loading market overview" className="motion-safe:animate-pulse p-6 text-sm text-muted-foreground">
          {mode === "preview" ? "Loading sample market data…" : "Loading market data…"}
        </Card>
      )}
      {snapshot.status === "error" && (
        <DataState error title="Market overview could not load" description={mode === "preview" ? "Try loading the demo snapshot again." : "The market API did not return an available snapshot."}
          action={<Button variant="outline" onClick={retry}>Retry overview</Button>} />
      )}
      {snapshot.status === "ready" && (
        <>
          <MarketSession overview={snapshot.data.overview} />
          {overviewItems.length > 0 && <MarketOverviewCards items={overviewItems} activeId={activeId} onSelect={selectInstrument} />}
          <div className="grid items-start gap-4 min-[1160px]:grid-cols-[minmax(0,2.05fr)_minmax(18.5rem,1fr)] sm:gap-5">
            {instrument && selectedQuote ? (
              <MarketChartPanel instrument={instrument} quote={selectedQuote} request={request} mode={mode} watched={watchlist.includes(instrument.id)}
                onTimeframe={selectTimeframe} onToggle={toggleWatchlist} onRestore={() => selectScenario("ready")} />
            ) : (
              <DataState title="No quotes available" description={instrument ? "Select a different instrument to view its chart." : "The market snapshot has no instruments with quotes."}
                action={<Button variant="outline" onClick={retry}>Refresh overview</Button>} />
            )}
            <MarketWatchlist instruments={instruments} quotes={quotes} activeId={activeId} ids={watchlist}
              onSelect={selectInstrument} onToggle={toggleWatchlist} onFind={openSearch} />
          </div>
          {instrument && selectedQuote && <InstrumentDetails instrument={instrument} quote={selectedQuote} />}
          <InstrumentSearch open={searchOpen} onOpenChange={setSearchOpen} instruments={instruments} watchlist={watchlist}
            onSelect={selectInstrument} onToggle={toggleWatchlist} onClose={() => searchOpener.current?.focus()} />
        </>
      )}
    </div>
  );
}
