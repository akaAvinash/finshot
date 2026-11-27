"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import { getBrokerPortfolio, type BrokerPortfolio } from "@/lib/api/broker-connections-client";
import { stagingError } from "@/lib/api/staging-client";
import { formatBrokerTime } from "@/lib/brokers";

function PortfolioSection({ title, columns, rows }: { title: string; columns: string[]; rows: string[][] | null }) {
  return <section className="min-w-0 space-y-2">
    <h3 className="text-sm font-semibold">{title}</h3>
    {rows === null ? <p className="text-xs text-muted-foreground">Permission unavailable for this connection.</p> :
      rows.length === 0 ? <p className="text-xs text-muted-foreground">No records in the stored snapshot.</p> :
      <div role="region" aria-label={`${title} table`} tabIndex={0} className="overflow-x-auto">
        <Table className="whitespace-nowrap">
          <thead><tr>{columns.map((name) => <TableHead key={name} scope="col">{name}</TableHead>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr key={index}>{row.map((value, column) =>
            <TableCell key={columns[column]} className="tabular-nums">{value}</TableCell>)}</tr>)}</tbody>
        </Table>
      </div>}
  </section>;
}

export function BrokerPortfolioPanel({ connectionId, account, onClose }: { connectionId: string; account: string; onClose: () => void }) {
  const [result, setResult] = useState<{ data: BrokerPortfolio } | { error: string }>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    void getBrokerPortfolio(connectionId, controller.signal).then((data) => {
      if (!controller.signal.aborted) setResult({ data });
    }, (error: unknown) => {
      if (!controller.signal.aborted) setResult({ error: stagingError(error, "The stored broker portfolio could not load.") });
    });
    return () => controller.abort();
  }, [attempt, connectionId]);

  const data = result && "data" in result ? result.data : undefined;
  return <Card aria-labelledby="broker-portfolio" className="min-w-0 space-y-4 p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h2 id="broker-portfolio" className="font-semibold">Stored portfolio · {account}</h2>
      <Button variant="ghost" size="sm" onClick={onClose}>Close portfolio</Button>
    </div>
    {!result && <p role="status" className="text-sm text-muted-foreground">Loading demo portfolio…</p>}
    {result && "error" in result && <div className="space-y-2"><p role="alert" className="text-sm text-negative">{result.error}</p>
      <Button variant="outline" size="sm" onClick={() => { setResult(undefined); setAttempt((value) => value + 1); }}>Retry portfolio</Button>
    </div>}
    {data && <>
      <p className="text-sm text-muted-foreground">{data.asOf ? <>Read-only demo snapshot · <time dateTime={data.asOf}>{formatBrokerTime(data.asOf)}</time></> : "Sync the account to populate the demo portfolio."}</p>
      <PortfolioSection title="Funds (INR)" columns={["Available", "Used", "Total"]}
        rows={data.funds && [[data.funds.available, data.funds.used, data.funds.total]]} />
      <PortfolioSection title="Holdings" columns={["Instrument", "Quantity", "Average price", "Last price"]}
        rows={data.holdings?.map((row) => [row.instrument.providerSymbol, row.quantity, row.averagePrice, row.lastPrice ?? "—"]) ?? null} />
      <PortfolioSection title="Positions" columns={["Instrument", "Product", "Quantity", "Average price", "Realised P&L", "Unrealised P&L"]}
        rows={data.positions?.map((row) => [row.instrument.providerSymbol, row.product, row.quantity, row.averagePrice, row.realisedPnl, row.unrealisedPnl]) ?? null} />
      <PortfolioSection title="Orders" columns={["Instrument", "Side", "Quantity", "Filled", "Price", "Status"]}
        rows={data.orders?.map((row) => [row.instrument.providerSymbol, row.side, row.quantity, row.filledQuantity, row.price ?? "—", row.status]) ?? null} />
    </>}
  </Card>;
}
