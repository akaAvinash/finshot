import { Activity, ArrowDownRight, ArrowRight, ArrowUpRight, Clock3, Info } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import type { Instrument, InstrumentQuote, MarketOverview } from "@/lib/api/market-types";
import { formatInr, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { formatMarketTime, formatSessionTime, formatVolume } from "./market-format";

const trends = {
  up: { icon: ArrowUpRight, label: "Up", color: "text-positive" },
  down: { icon: ArrowDownRight, label: "Down", color: "text-negative" },
  flat: { icon: ArrowRight, label: "Flat", color: "text-muted-foreground" },
};

export function QuoteChange({ quote, includeAmount = false }: { quote: InstrumentQuote; includeAmount?: boolean }) {
  const { icon: Icon, color } = trends[quote.trend];
  return (
    <span className={cn("inline-flex flex-wrap items-center gap-x-1 whitespace-nowrap text-xs font-medium tabular-nums", color)}>
      <Icon aria-hidden className="size-3.5" />
      {includeAmount && <span>{formatInr(quote.change, true)}</span>}
      <span>{includeAmount ? `(${formatPercent(quote.changePercent)})` : formatPercent(quote.changePercent)}</span>
    </span>
  );
}

export function MarketSession({ overview }: { overview: MarketOverview }) {
  const { session, asOf } = overview;
  const labels = { closed: "Market closed", open: "Market open", preopen: "Pre-open" };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
      <Status tone={session.status === "open" ? "positive" : "neutral"} dot>{labels[session.status]}</Status>
      <span className="flex items-center gap-1.5">
        <Clock3 className="size-3.5" aria-hidden />
        {session.exchange} session {formatSessionTime(session.opensAt)}–{formatSessionTime(session.closesAt)} IST
      </span>
      <time dateTime={asOf} className="sm:ml-auto">Demo snapshot · {formatMarketTime(asOf)}</time>
    </div>
  );
}

type OverviewItem = { instrument: Instrument; quote: InstrumentQuote };

export function MarketOverviewCards({ items, activeId, onSelect }: {
  items: OverviewItem[];
  activeId: string;
  onSelect: (id: string) => void;
}) {
  return (
    <section aria-labelledby="market-overview-heading" className="space-y-3">
      <h2 id="market-overview-heading" className="flex items-center gap-2 text-sm font-semibold">
        <Activity aria-hidden className="size-4 text-accent-foreground" /> Market overview
      </h2>
      <div className="grid grid-cols-2 gap-3 min-[800px]:grid-cols-4 sm:gap-4">
        {items.map(({ instrument, quote }) => (
          <button
            key={instrument.id}
            type="button"
            aria-label={`View ${instrument.symbol} market overview`}
            aria-pressed={instrument.id === activeId}
            onClick={() => onSelect(instrument.id)}
            className={cn(
              "min-w-0 rounded-xl border bg-card px-3 py-3.5 text-left transition-colors sm:px-4",
              instrument.id === activeId ? "border-primary/55" : "border-border hover:border-primary/40",
            )}
          >
            <span className="block truncate text-xs font-semibold tracking-wide text-muted-foreground">{instrument.symbol}</span>
            <span className="mt-1.5 block text-lg font-semibold tracking-tight tabular-nums sm:text-xl">{formatInr(quote.price)}</span>
            <QuoteChange quote={quote} includeAmount />
            <span className="mt-2 flex flex-wrap items-center justify-between gap-x-2 border-t border-border pt-2 text-xs text-muted-foreground">
              <span>Vol <span className="tabular-nums" title={quote.volume === null ? "Index volume unavailable" : formatVolume(quote.volume)}>{formatVolume(quote.volume, true)}</span></span>
              <span className={trends[quote.trend].color}>{trends[quote.trend].label}</span>
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

export function InstrumentDetails({ instrument, quote }: { instrument: Instrument; quote: InstrumentQuote }) {
  const metrics = [
    { label: "Previous close", value: formatInr(quote.previousClose) },
    { label: "Open", value: formatInr(quote.open) },
    { label: "Day high", value: formatInr(quote.high) },
    { label: "Day low", value: formatInr(quote.low) },
    { label: "Volume", value: quote.volume === null ? "Unavailable" : formatVolume(quote.volume) },
    { label: "Trend", value: trends[quote.trend].label, color: trends[quote.trend].color },
  ];

  return (
    <Card aria-labelledby="instrument-details-heading" className="overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-4 sm:px-5">
        <div>
          <h2 id="instrument-details-heading" className="flex items-center gap-2 text-base font-semibold tracking-tight">
            <Info aria-hidden className="size-4 text-accent-foreground" /> Instrument details
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">{instrument.name} · {instrument.exchange} · {instrument.currency}</p>
        </div>
        <Status>{instrument.kind === "index" ? "Index" : "Equity"}</Status>
      </header>
      <dl className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
        {metrics.map(({ label, value, color }) => (
          <div key={label} className="px-4 py-3 sm:px-5 sm:py-4">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className={cn("mt-1 text-sm font-semibold tabular-nums", color)}>{value}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}
