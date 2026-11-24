import { BookOpen, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/input";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { ReportTrade } from "@/lib/api/report-types";
import { formatInr, formatSnapshotDate } from "@/lib/format";
import { formatReportTime, reportDay, reportTradePnl } from "@/lib/reporting";
import { cn } from "@/lib/utils";

const pageSize = 8;

export function ReportJournal({ trades, day }: { trades: readonly ReportTrade[]; day: string | null }) {
  const [filter, setFilter] = useState("all");
  const [page, setPage] = useState(0);
  const matching = trades.flatMap((trade) => {
    if (day && reportDay(trade.closedAt) !== day) return [];
    const pnl = reportTradePnl(trade);
    if ((filter === "profit" && pnl.netPaise <= 0) || (filter === "loss" && pnl.netPaise >= 0)) return [];
    return [{ trade, pnl }];
  });
  const lastPage = Math.max(0, Math.ceil(matching.length / pageSize) - 1);
  const visible = matching.slice(page * pageSize, (page + 1) * pageSize);

  return (
    <Card className="overflow-hidden" aria-labelledby="trade-journal-heading">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4 sm:px-5">
        <div>
          <h2 id="trade-journal-heading" className="flex items-center gap-2 font-semibold"><BookOpen aria-hidden className="size-4 text-accent-foreground" /> Trade journal</h2>
          <p className="mt-1 text-xs text-muted-foreground">{matching.length} closed trades · {day ? formatSnapshotDate(day) : "Selected period"} · All times IST</p>
        </div>
        <Label htmlFor="report-outcome" className="sr-only">Filter trades by outcome</Label>
        <select id="report-outcome" className="h-11 rounded-lg border border-input bg-background px-3 text-sm" value={filter}
          onChange={({ target }) => { setFilter(target.value); setPage(0); }}>
          <option value="all">All outcomes</option><option value="profit">Profitable</option><option value="loss">Losses</option>
        </select>
      </div>
      {visible.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No closed trades match this view.</p> : (
        <div className="relative overflow-x-auto" role="region" aria-label="Demo trade journal table" tabIndex={0}>
          <Table>
            <caption className="sr-only">Closed demo trades after brokerage and taxes</caption>
            <thead className="border-b border-border bg-surface-raised/60"><tr>
              <TableHead>Closed at</TableHead><TableHead>Symbol</TableHead><TableHead>Position</TableHead><TableHead>Broker</TableHead>
              <TableHead>Strategy</TableHead><TableHead>Qty</TableHead><TableHead>Gross P&L</TableHead><TableHead>Charges</TableHead><TableHead>Net realized</TableHead>
            </tr></thead>
            <tbody>
              {visible.map(({ trade, pnl }) => <tr key={trade.id} className="border-b border-border tabular-nums last:border-b-0">
                <TableCell><time dateTime={trade.closedAt}>{formatReportTime(trade.closedAt)}</time></TableCell>
                <TableCell className="font-medium">{trade.symbol}</TableCell><TableCell><Status>{trade.side === "long" ? "Long" : "Short"}</Status></TableCell>
                <TableCell>{trade.broker}</TableCell><TableCell>{trade.strategy}</TableCell><TableCell>{trade.quantity}</TableCell>
                <TableCell>{formatInr(pnl.grossPaise / 100, true)}</TableCell><TableCell>{formatInr(pnl.chargesPaise / 100)}</TableCell>
                <TableCell className={cn("font-semibold", pnl.netPaise > 0 && "text-positive", pnl.netPaise < 0 && "text-negative")}>{formatInr(pnl.netPaise / 100, true)}</TableCell>
              </tr>)}
            </tbody>
          </Table>
        </div>
      )}
      {lastPage > 0 && <div className="flex items-center justify-between gap-3 border-t border-border px-4 py-2 sm:px-5">
        <span className="text-xs text-muted-foreground" aria-live="polite">Page {page + 1} of {lastPage + 1}</span>
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" aria-label="Previous trade page" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft aria-hidden /></Button>
          <Button variant="ghost" size="icon" aria-label="Next trade page" disabled={page >= lastPage} onClick={() => setPage(page + 1)}><ChevronRight aria-hidden /></Button>
        </div>
      </div>}
    </Card>
  );
}
