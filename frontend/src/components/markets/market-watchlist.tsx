"use client";

import { useId, useState, type MouseEvent } from "react";
import { Plus, Search, Star } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input, Label } from "@/components/ui/input";
import type { Instrument, InstrumentQuote } from "@/lib/api/market-types";
import { formatInr } from "@/lib/format";
import { searchInstruments } from "@/lib/market/search";
import { cn } from "@/lib/utils";
import { WatchlistToggle } from "./instrument-search";
import { QuoteChange } from "./market-summary";

export function MarketWatchlist({ instruments, quotes, activeId, ids, onSelect, onToggle, onFind }: {
  instruments: Instrument[];
  quotes: ReadonlyMap<string, InstrumentQuote>;
  activeId: string;
  ids: string[];
  onSelect: (id: string) => void;
  onToggle: (instrument: Instrument, add: boolean) => void;
  onFind: (event: MouseEvent<HTMLButtonElement>) => void;
}) {
  const inputId = useId();
  const [query, setQuery] = useState("");
  const saved = ids.flatMap((id) => {
    const instrument = instruments.find((item) => item.id === id);
    return instrument ? [instrument] : [];
  });
  const results = searchInstruments(saved, query);

  return (
    <Card aria-labelledby="market-watchlist-heading" className="min-w-0 overflow-hidden">
      <header className="flex items-center justify-between gap-2 px-4 py-4">
        <h2 id="market-watchlist-heading" className="flex items-center gap-2 text-base font-semibold tracking-tight">
          <Star aria-hidden className="size-4 text-accent-foreground" /> Watchlist
          <span className="text-xs font-medium text-muted-foreground">{saved.length}</span>
        </h2>
        <Button variant="outline" size="sm" onClick={onFind}><Plus aria-hidden /> Add instrument</Button>
      </header>
      <div className="relative mx-4 mb-3">
        <Label htmlFor={inputId} className="sr-only">Search watchlist</Label>
        <Search aria-hidden className="pointer-events-none absolute left-3 top-3 size-4 text-muted-foreground" />
        <Input id={inputId} type="search" value={query} onChange={(event) => setQuery(event.target.value)}
          className="h-10 pl-9" placeholder="Search watchlist" />
      </div>
      {results.length ? (
        <ul aria-label="Saved instruments" className="max-h-81 space-y-1.5 overflow-y-auto px-4 pb-4">
          {results.map((instrument) => {
            const quote = quotes.get(instrument.id);
            const active = instrument.id === activeId;

            return (
              <li key={instrument.id} className={cn("flex min-w-0 items-center gap-1 rounded-lg border", active ? "border-primary/45 bg-primary/8" : "border-border")}>
                <button type="button" aria-label={`View ${instrument.symbol} from watchlist`} aria-pressed={active}
                  onClick={() => onSelect(instrument.id)}
                  className="flex min-w-0 flex-1 items-center justify-between gap-2 rounded-l-lg px-2.5 py-2.5 text-left hover:bg-surface-raised">
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-semibold">{instrument.symbol}</span>
                    <span className="block truncate text-xs text-muted-foreground">{instrument.name}</span>
                  </span>
                  {quote && (
                    <span className="flex shrink-0 flex-col items-end">
                      <span className="text-sm font-medium tabular-nums">{formatInr(quote.price)}</span>
                      <QuoteChange quote={quote} />
                    </span>
                  )}
                </button>
                <WatchlistToggle instrument={instrument} saved onToggle={onToggle} />
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="px-4 pb-6 pt-3 text-center text-sm text-muted-foreground">
          {saved.length ? "No saved instruments match your search." : "Your watchlist is empty. Add an instrument to track it here."}
        </div>
      )}
    </Card>
  );
}
