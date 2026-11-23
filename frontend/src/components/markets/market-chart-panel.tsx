"use client";

import { CandlestickChart as CandleIcon, CircleAlert, Clock3, DatabaseZap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { marketTimeframes, type Instrument, type InstrumentQuote, type MarketTimeframe } from "@/lib/api/market-types";
import { formatInr } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CandlestickChart } from "./candlestick-chart";
import { WatchlistToggle } from "./instrument-search";
import { formatMarketTime } from "./market-format";
import { QuoteChange } from "./market-summary";
import { useMarketCandles, type ChartRequest } from "./use-market-data";

export function MarketChartPanel({ instrument, quote, request, watched, onTimeframe, onToggle, onRestore }: {
  instrument: Instrument;
  quote: InstrumentQuote;
  request: ChartRequest;
  watched: boolean;
  onTimeframe: (timeframe: MarketTimeframe) => void;
  onToggle: (instrument: Instrument, add: boolean) => void;
  onRestore: () => void;
}) {
  const result = useMarketCandles(request);
  const { timeframe } = request;
  const empty = result.status === "ready" && !result.data.candles.length;

  return (
    <Card aria-labelledby="market-chart-heading" className="min-w-0 overflow-hidden">
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-3 px-4 pb-4 pt-4 sm:px-5 sm:pt-5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <CandleIcon aria-hidden className="size-4 text-accent-foreground" />
            <h2 id="market-chart-heading" className="text-lg font-semibold tracking-tight">{instrument.symbol}</h2>
            <Status>{instrument.exchange}</Status>
          </div>
          <p className="mt-0.5 text-xs text-muted-foreground">{instrument.name}</p>
          <div className="mt-2 flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <p className="text-2xl font-semibold tracking-tight tabular-nums">{formatInr(quote.price)}</p>
            <QuoteChange quote={quote} includeAmount />
          </div>
        </div>
        <WatchlistToggle instrument={instrument} saved={watched} onToggle={onToggle} />
      </header>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 border-y border-border px-4 py-2 sm:px-5">
        <div role="group" aria-label="Chart timeframe" className="flex flex-wrap gap-1">
          {marketTimeframes.map((option) => (
            <button key={option} type="button" aria-pressed={option === timeframe} onClick={() => onTimeframe(option)}
              className={cn("min-h-8 min-w-8 rounded-md px-1.5 text-xs font-semibold transition-colors sm:min-w-9 sm:px-2",
                option === timeframe ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-surface-raised hover:text-foreground")}>
              {option}
            </button>
          ))}
        </div>
        <span className="whitespace-nowrap text-xs text-muted-foreground">INR · IST</span>
      </div>

      {result.status === "loading" && (
        <div role="status" aria-label="Loading chart" className="m-4 flex h-66 animate-pulse items-center justify-center rounded-lg border border-border bg-background/50 text-sm text-muted-foreground sm:h-76 motion-reduce:animate-none">
          Loading chart…
        </div>
      )}

      {(result.status === "error" || empty) && (
        <div role={result.status === "error" ? "alert" : "status"} className="flex min-h-72 flex-col items-center justify-center px-5 py-8 text-center sm:min-h-82">
          {result.status === "error" ? <CircleAlert aria-hidden className="size-6 text-negative" /> : <DatabaseZap aria-hidden className="size-6 text-accent-foreground" />}
          <p className="mt-3 font-semibold">{result.status === "error" ? "Chart could not load" : "No candles available"}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {result.status === "error" ? "The simulated chart request failed." : "This demo response has no candles for the selected timeframe."}
          </p>
          <Button variant="outline" size="sm" className="mt-4" onClick={onRestore}>
            {result.status === "error" ? "Retry chart" : "Load demo candles"}
          </Button>
        </div>
      )}

      {result.status === "ready" && !empty && (
        <>
          {result.data.freshness === "stale" && (
            <div role="status" className="mx-4 mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primary/35 bg-primary/8 p-2.5 text-xs sm:mx-5">
              <p className="flex items-center gap-2"><Clock3 aria-hidden className="size-4 shrink-0 text-accent-foreground" /> Showing stale demo candles.</p>
              <Button variant="outline" size="sm" onClick={onRestore}>Load latest candles</Button>
            </div>
          )}
          <CandlestickChart candles={result.data.candles} timeframe={timeframe} />
          <p className="border-t border-border px-4 py-2.5 text-xs text-muted-foreground sm:px-5">
            Demo candles · <time dateTime={result.data.asOf}>{formatMarketTime(result.data.asOf)}</time>
          </p>
        </>
      )}
    </Card>
  );
}
