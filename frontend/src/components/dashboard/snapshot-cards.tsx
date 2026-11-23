import { Activity, ArrowDownRight, ArrowUpRight, ChartNoAxesColumnIncreasing, Crosshair, Minus, TrendingUp, Wallet } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { DashboardSnapshot, MarketQuote, Trade } from "@/lib/api/types";
import { formatInr, formatPercent, formatPrice } from "@/lib/format";
import { cn } from "@/lib/utils";

function Change({ value, compact = false }: { value: number; compact?: boolean }) {
  const Icon = value > 0 ? ArrowUpRight : value < 0 ? ArrowDownRight : Minus;

  return (
    <span className={cn(
      "inline-flex items-center gap-0.5 whitespace-nowrap text-xs font-semibold tabular-nums",
      value > 0 ? "text-positive" : value < 0 ? "text-negative" : "text-muted-foreground",
    )}>
      {!compact && <Icon aria-hidden className="size-3.5" />}
      {formatPercent(value)}
    </span>
  );
}

export function MarketStrip({ indices }: { indices: MarketQuote[] }) {
  return (
    <Card aria-label="Sample market indices" className="grid divide-y divide-border min-[520px]:grid-cols-3 min-[520px]:divide-x min-[520px]:divide-y-0">
      {indices.map((quote) => (
        <div key={quote.symbol} className="flex min-w-0 flex-wrap items-baseline justify-between gap-x-2 gap-y-1 px-4 py-3 sm:py-3.5">
          <span className="text-xs font-semibold tracking-wide text-muted-foreground">{quote.symbol}</span>
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="text-sm font-semibold tabular-nums">{formatPrice(quote.price)}</span>
            <Change value={quote.changePercent} />
          </div>
        </div>
      ))}
    </Card>
  );
}

export function Metrics({ data }: { data: DashboardSnapshot }) {
  const winRate = data.totalTrades ? ((data.winningTrades / data.totalTrades) * 100).toFixed(1) : "0.0";

  const metrics = [
    { label: "Portfolio value", value: formatInr(data.portfolioValue), detail: "Sample net equity", icon: Wallet },
    { label: "Day P&L", value: formatInr(data.dayPnl, true), detail: "vs. previous close", change: data.dayReturn, pnl: data.dayPnl, icon: TrendingUp },
    { label: "Month P&L", value: formatInr(data.monthPnl, true), detail: "month to date", change: data.monthReturn, pnl: data.monthPnl, icon: ChartNoAxesColumnIncreasing },
    { label: "Win rate", value: `${winRate}%`, detail: `${data.winningTrades} of ${data.totalTrades} sample trades`, icon: Crosshair },
  ];

  return (
    <section aria-label="Portfolio metrics" className="grid grid-cols-2 gap-3 sm:gap-4 min-[800px]:grid-cols-4">
      {metrics.map(({ label, value, detail, change, pnl, icon: Icon }) => (
        <Card key={label} className="p-3.5 sm:p-4">
          <div className="flex items-center justify-between gap-1">
            <h2 className="text-xs font-medium text-muted-foreground sm:text-sm">{label}</h2>
            <span className="grid size-7 shrink-0 place-items-center rounded-md border border-primary/15 bg-primary/9 text-accent-foreground sm:size-8">
              <Icon aria-hidden className="size-3.5 sm:size-4" />
            </span>
          </div>
          <p className={cn(
            "mt-2 text-lg font-semibold tracking-[-0.05em] tabular-nums min-[380px]:text-xl sm:text-[1.6rem]",
            pnl !== undefined && (pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : undefined),
          )}>{value}</p>
          <p className="mt-1 flex flex-wrap items-baseline gap-x-1.5 gap-y-1 text-xs text-muted-foreground">
            {change !== undefined && <Change value={change} compact />}
            <span>{detail}</span>
          </p>
        </Card>
      ))}
    </section>
  );
}

export function Watchlist({ quotes }: { quotes: MarketQuote[] }) {
  return (
    <Card aria-labelledby="watchlist-heading" className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-4 sm:px-5">
        <div>
          <h2 id="watchlist-heading" className="flex items-center gap-2 text-base font-semibold tracking-tight">
            <Activity aria-hidden className="size-4 text-accent-foreground" /> Watchlist
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">Sample NSE equity quotes</p>
        </div>
        <Status>NSE</Status>
      </div>
      {quotes.length > 0 ? (
        <ul className="divide-y divide-border px-4 sm:px-5">
          {quotes.map(({ symbol, name, price, changePercent }) => (
            <li key={symbol} className="flex items-baseline justify-between gap-2 py-2.5">
              <div className="min-w-0">
                <p className="text-sm font-semibold">{symbol}</p>
                <p className="truncate text-xs text-muted-foreground" title={name}>{name}</p>
              </div>
              <div className="flex shrink-0 items-baseline gap-2 tabular-nums">
                <span className="text-sm font-medium">{formatPrice(price)}</span>
                <span className="min-w-13 text-right"><Change value={changePercent} compact /></span>
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <p className="p-5 text-sm text-muted-foreground">No sample quotes available.</p>
      )}
    </Card>
  );
}

export function RecentActivity({ trades }: { trades: Trade[] }) {
  return (
    <Card aria-labelledby="activity-heading" className="overflow-hidden">
      <div className="flex items-center justify-between gap-3 border-b border-border p-4 sm:px-5">
        <div>
          <h2 id="activity-heading" className="text-base font-semibold tracking-tight">Recent trades</h2>
          <p className="mt-1 text-xs text-muted-foreground">Trades from the sample session</p>
        </div>
        <Status>Simulated</Status>
      </div>
      {trades.length > 0 ? (
        <div tabIndex={0} role="region" aria-label="Recent trades table" className="overflow-x-auto focus-visible:outline-offset-[-3px]">
          <Table className="[&_td]:px-2 [&_th]:px-2 sm:[&_td]:px-4 sm:[&_th]:px-4">
            <thead className="border-b border-border bg-background/45">
              <tr>
                <TableHead>Instrument</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">P&L</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Time (IST)</TableHead>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {trades.map(({ id, symbol, side, quantity, price, pnl, timeIst }) => (
                <tr key={id}>
                  <th scope="row" className="whitespace-nowrap px-4 py-3.5 font-semibold">{symbol}</th>
                  <TableCell><Status tone={side === "Buy" ? "positive" : "neutral"}>{side}</Status></TableCell>
                  <TableCell className="text-right tabular-nums">{quantity}</TableCell>
                  <TableCell className={cn("text-right font-medium tabular-nums", pnl > 0 ? "text-positive" : pnl < 0 ? "text-negative" : undefined)}>
                    {formatInr(pnl, true)}
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{formatInr(price)}</TableCell>
                  <TableCell className="text-right text-muted-foreground tabular-nums">{timeIst}</TableCell>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : (
        <p className="px-5 py-7 text-sm text-muted-foreground">No trades are available in this sample snapshot.</p>
      )}
    </Card>
  );
}
