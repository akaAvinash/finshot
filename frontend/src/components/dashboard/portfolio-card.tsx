"use client";

import { useMemo, useState } from "react";
import { ChartNoAxesCombined } from "lucide-react";
import { Card } from "@/components/ui/card";
import type { PortfolioPoint } from "@/lib/api/types";
import { formatInr, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import { PortfolioChart } from "./portfolio-chart";

const ranges = [
  { label: "1W", description: "one week", days: 7 },
  { label: "1M", description: "one month", days: 30 },
  { label: "All", description: "all available sample dates", days: Infinity },
] as const;

export function PortfolioCard({ points }: { points: PortfolioPoint[] }) {
  const [range, setRange] = useState<(typeof ranges)[number]>(ranges[1]);
  const visible = useMemo(() => {
    if (!Number.isFinite(range.days)) return points;

    const lastDate = points.at(-1)?.date;
    if (!lastDate) return [];
    const cutoff = new Date(lastDate);
    cutoff.setUTCDate(cutoff.getUTCDate() - range.days);
    const startDate = cutoff.toISOString().slice(0, 10);
    return points.filter(({ date }) => date >= startDate);
  }, [points, range]);

  const first = visible[0]?.value;
  const last = visible.at(-1)?.value;
  const change = first && last !== undefined ? ((last - first) / first) * 100 : undefined;

  return (
    <Card aria-labelledby="portfolio-heading" className="flex flex-col overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 px-4 pt-4 sm:px-5 sm:pt-5">
        <div>
          <h2 id="portfolio-heading" className="flex items-center gap-2 text-base font-semibold tracking-tight">
            <ChartNoAxesCombined aria-hidden className="size-4 text-accent-foreground" /> Portfolio performance
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">Sample equity curve · INR</p>
        </div>
        <div role="group" aria-label="Portfolio period" className="inline-flex rounded-lg border border-border bg-background p-0.5">
          {ranges.map((item) => (
            <button
              key={item.label}
              type="button"
              aria-pressed={range.label === item.label}
              onClick={() => setRange(item)}
              className={cn(
                "min-h-8 min-w-9 rounded-md px-2 text-xs font-medium transition-colors",
                range.label === item.label
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-surface-raised hover:text-foreground",
              )}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>
      {last !== undefined && change !== undefined ? (
        <>
          <div className="mx-4 mb-1 mt-3 flex flex-wrap items-baseline gap-x-2 gap-y-1 sm:mx-5">
            <p className="text-2xl font-semibold tracking-[-0.055em] tabular-nums">{formatInr(last)}</p>
            <p className={cn("text-xs font-medium tabular-nums", change >= 0 ? "text-positive" : "text-negative")}>
              {formatPercent(change)} <span className="text-muted-foreground">over {range.description}</span>
            </p>
          </div>
          <div className="relative mx-2.5 mb-3 min-h-49 flex-1 sm:mx-4 sm:min-h-51">
            <PortfolioChart points={visible} />
          </div>
        </>
      ) : (
        <p className="px-5 py-10 text-sm text-muted-foreground">No portfolio points for this period.</p>
      )}
    </Card>
  );
}
