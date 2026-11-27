"use client";

import { useId, useState } from "react";
import { Search, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import type { Instrument, MarketSource } from "@/lib/api/market-types";
import { searchInstruments } from "@/lib/market/search";
import { cn } from "@/lib/utils";

export function WatchlistToggle({ instrument, saved, onToggle }: {
  instrument: Instrument;
  saved: boolean;
  onToggle: (instrument: Instrument, add: boolean) => void;
}) {
  const label = saved ? `Remove ${instrument.symbol} from watchlist` : `Add ${instrument.symbol} to watchlist`;

  return (
    <Button variant="ghost" size="icon" aria-label={label} title={label} onClick={() => onToggle(instrument, !saved)}
      className={cn("shrink-0", saved && "text-accent-foreground hover:text-accent-foreground")}>
      <Star aria-hidden className={saved ? "fill-current" : undefined} />
    </Button>
  );
}

export function InstrumentSearch({ open, onOpenChange, instruments, source, watchlist, onSelect, onToggle, onClose }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instruments: Instrument[];
  source: MarketSource;
  watchlist: string[];
  onSelect: (id: string) => void;
  onToggle: (instrument: Instrument, add: boolean) => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && (
        <DialogContent className="flex max-w-lg flex-col gap-4" onCloseAutoFocus={(event) => {
          event.preventDefault();
          onClose();
        }}>
          <div>
            <DialogTitle>Find an instrument</DialogTitle>
            <DialogDescription>{source === "demo" ? "Demo catalog. Search sample NSE instruments by symbol or name." : "Search NSE instruments by symbol or name."}</DialogDescription>
          </div>
          <SearchResults instruments={instruments} watchlist={watchlist} onSelect={(id) => {
            onSelect(id);
            onOpenChange(false);
          }} onToggle={onToggle} />
        </DialogContent>
      )}
    </Dialog>
  );
}

function SearchResults({ instruments, watchlist, onSelect, onToggle }: {
  instruments: Instrument[];
  watchlist: string[];
  onSelect: (id: string) => void;
  onToggle: (instrument: Instrument, add: boolean) => void;
}) {
  const [query, setQuery] = useState("");
  const inputId = useId();
  const results = searchInstruments(instruments, query);

  return (
    <>
      <div className="relative">
        <Label htmlFor={inputId} className="sr-only">Search instruments</Label>
        <Search aria-hidden className="pointer-events-none absolute left-3 top-3.5 size-4 text-muted-foreground" />
        <Input id={inputId} type="search" value={query} onChange={(event) => setQuery(event.target.value)}
          placeholder="Try NIFTY 50 or HDFC Bank" className="pl-9" />
      </div>
      <p className="sr-only" role="status">{results.length} instruments found</p>
      {results.length > 0 ? (
        <ul aria-label="Instruments" className="-mx-1 max-h-[45dvh] divide-y divide-border overflow-y-auto px-1">
          {results.map((instrument) => (
            <li key={instrument.id} className="flex min-w-0 items-center gap-1 py-1">
              <button type="button" aria-label={`Select ${instrument.symbol}`} onClick={() => onSelect(instrument.id)}
                className="min-w-0 flex-1 rounded-md px-2 py-2 text-left hover:bg-surface-raised">
                <span className="block truncate text-sm font-semibold">{instrument.symbol}</span>
                <span className="block truncate text-xs text-muted-foreground">{instrument.name} · {instrument.exchange}</span>
              </button>
              <WatchlistToggle instrument={instrument} saved={watchlist.includes(instrument.id)} onToggle={onToggle} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="rounded-lg border border-border px-3 py-8 text-center text-sm text-muted-foreground">No instruments match your search.</p>
      )}
    </>
  );
}
