"use client";

import { Activity, ClipboardList, History } from "lucide-react";
import { Tabs } from "radix-ui";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { PaperSnapshot, PaperOrder } from "@/lib/api/auto-trading-types";
import { formatInr } from "@/lib/format";

export const paperTime = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
});

const orderState = {
  queued: { label: "Queued", tone: "accent" },
  held: { label: "Held", tone: "neutral" },
  cancelled: { label: "Cancelled", tone: "negative" },
} as const satisfies Record<PaperOrder["status"], { label: string; tone: "accent" | "neutral" | "negative" }>;

const tabs = [
  { value: "queue", label: "Order queue", icon: ClipboardList },
  { value: "trades", label: "Trade log", icon: Activity },
  { value: "events", label: "Event log", icon: History },
];

export function PaperActivity({ snapshot }: { snapshot: PaperSnapshot }) {
  return (
    <Card aria-label="Paper trading activity" className="overflow-hidden">
      <Tabs.Root defaultValue="queue">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-3 py-3 sm:px-5">
          <Tabs.List aria-label="Paper activity views" className="flex flex-wrap items-center gap-1">
            {tabs.map(({ value, label, icon: Icon }) => (
              <Tabs.Trigger key={value} value={value}
                className="inline-flex min-h-10 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-surface-raised data-[state=active]:bg-primary/13 data-[state=active]:text-accent-foreground sm:px-3 sm:text-sm">
                <Icon aria-hidden className="hidden size-3.5 sm:block" />{label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <Status tone="accent">Paper demo</Status>
        </div>

        <Tabs.Content value="queue">
          {snapshot.orders.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No paper orders queued.</p> : (
            <div role="region" aria-label="Paper order queue table" tabIndex={0} className="overflow-x-auto focus-visible:outline-offset-[-3px]">
              <Table className="[&_td]:px-2 [&_th]:px-2 sm:[&_td]:px-4 sm:[&_th]:px-4">
                <thead className="border-b border-border bg-background/50"><tr>
                  <TableHead>Instrument</TableHead><TableHead>Status</TableHead><TableHead>Risk approval</TableHead>
                  <TableHead>Side</TableHead><TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Limit price</TableHead>
                </tr></thead>
                <tbody className="divide-y divide-border">
                  {snapshot.orders.map((order) => (
                    <tr key={order.id}>
                      <th scope="row" className="whitespace-nowrap px-4 py-3 text-sm font-semibold">{order.instrument}<span className="ml-2 hidden text-xs font-normal text-muted-foreground sm:inline">{order.id}</span></th>
                      <TableCell><Status tone={orderState[order.status].tone}>{orderState[order.status].label}</Status></TableCell>
                      <TableCell><Status tone={order.approval === "approved" ? "positive" : "neutral"}>{order.approval === "approved" ? "Approved" : "Pending"}</Status></TableCell>
                      <TableCell>{order.side}</TableCell>
                      <TableCell className="text-right tabular-nums">{order.quantity}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatInr(order.limitPaise / 100)}</TableCell>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </Tabs.Content>

        <Tabs.Content value="trades">
          {snapshot.trades.length === 0 ? <p className="p-5 text-sm text-muted-foreground">No completed paper trades.</p> : (
            <div role="region" aria-label="Paper trade log table" tabIndex={0} className="overflow-x-auto focus-visible:outline-offset-[-3px]">
              <Table>
                <thead className="border-b border-border bg-background/50"><tr>
                  <TableHead>Instrument</TableHead><TableHead>Side</TableHead><TableHead className="text-right">P&amp;L</TableHead>
                  <TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Fill</TableHead><TableHead className="text-right">Time (IST)</TableHead>
                </tr></thead>
                <tbody className="divide-y divide-border">
                  {snapshot.trades.map((trade) => (
                    <tr key={trade.id}>
                      <th scope="row" className="whitespace-nowrap px-4 py-3 text-sm font-semibold">{trade.instrument}</th>
                      <TableCell>{trade.side}</TableCell>
                      <TableCell className={`text-right tabular-nums ${trade.pnlPaise >= 0 ? "text-positive" : "text-negative"}`}>{formatInr(trade.pnlPaise / 100, true)}</TableCell>
                      <TableCell className="text-right tabular-nums">{trade.quantity}</TableCell>
                      <TableCell className="text-right tabular-nums">{formatInr(trade.fillPaise / 100)}</TableCell>
                      <TableCell className="text-right tabular-nums"><time dateTime={trade.filledAt}>{paperTime.format(new Date(trade.filledAt))}</time></TableCell>
                    </tr>
                  ))}
                </tbody>
              </Table>
            </div>
          )}
        </Tabs.Content>

        <Tabs.Content value="events">
          <ol className="divide-y divide-border px-4 sm:px-5">
            {[...snapshot.events].reverse().map((event) => (
              <li key={event.id} className="flex gap-3 py-3 text-sm">
                <time dateTime={event.at} className="w-23 shrink-0 text-xs tabular-nums text-muted-foreground">{paperTime.format(new Date(event.at))} IST</time>
                <span>{event.message}</span>
              </li>
            ))}
          </ol>
        </Tabs.Content>
      </Tabs.Root>
    </Card>
  );
}
