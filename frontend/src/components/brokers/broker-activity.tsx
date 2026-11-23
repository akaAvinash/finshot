import { History } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { BrokerAction, BrokerEvent } from "@/lib/api/broker-types";
import { brokerNames, formatBrokerTime } from "@/lib/brokers";

const actionLabel: Record<BrokerAction, string> = {
  connect: "Account connected",
  reconnect: "Session reconnected",
  sync: "Account synced",
  disconnect: "Account disconnected",
};

export function BrokerActivity({ events }: { events: readonly BrokerEvent[] }) {
  return (
    <Card aria-labelledby="broker-activity-heading" className="overflow-hidden">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-4 sm:px-5">
        <h2 id="broker-activity-heading" className="flex items-center gap-2 font-semibold tracking-tight">
          <History aria-hidden className="size-4 text-accent-foreground" /> Connection activity
        </h2>
        <Status tone="accent">Demo events</Status>
      </header>
      {events.length ? (
        <div role="region" tabIndex={0} aria-label="Broker activity table" className="overflow-x-auto focus-visible:outline-offset-[-3px]">
          <Table className="[&_td]:px-2.5 [&_th]:px-2.5 sm:[&_td]:px-4 sm:[&_th]:px-4">
            <thead className="border-b border-border bg-background/50">
              <tr><TableHead>Broker</TableHead><TableHead>Activity</TableHead><TableHead className="text-right">Time (IST)</TableHead></tr>
            </thead>
            <tbody className="divide-y divide-border">
              {[...events].reverse().map((event) => (
                <tr key={event.id}>
                  <th scope="row" className="whitespace-nowrap py-3 text-sm font-semibold">{brokerNames[event.provider]}</th>
                  <TableCell>{actionLabel[event.action]}</TableCell>
                  <TableCell className="text-right text-xs tabular-nums text-muted-foreground">
                    <time dateTime={event.at}>{formatBrokerTime(event.at)}</time>
                  </TableCell>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      ) : <p className="p-5 text-sm text-muted-foreground">No connection activity yet.</p>}
    </Card>
  );
}
