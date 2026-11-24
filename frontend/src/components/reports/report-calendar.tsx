import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { formatInr, formatSnapshotDate } from "@/lib/format";
import { dailyReport } from "@/lib/reporting";
import { cn } from "@/lib/utils";

const weekdayLabels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const monthName = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });

function stepMonth(month: string, step: number) {
  const date = new Date(`${month}-01T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + step);
  return date.toISOString().slice(0, 7);
}

export function ReportCalendar({ days, range, selected, onSelect }: {
  days: ReturnType<typeof dailyReport>;
  range: { from: string; to: string };
  selected: string | null;
  onSelect: (day: string | null) => void;
}) {
  const [month, setMonth] = useState(range.to.slice(0, 7));
  const start = new Date(`${month}-01T00:00:00Z`);
  const next = stepMonth(month, 1);
  const leading = (start.getUTCDay() + 6) % 7;
  const count = new Date(Date.parse(`${next}-01T00:00:00Z`) - 86_400_000).getUTCDate();
  const byDate = new Map(days.map((day) => [day.date, day]));
  const selectedEntry = selected ? byDate.get(selected) : undefined;

  return (
    <Card aria-labelledby="report-calendar-heading" className="p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="report-calendar-heading" className="flex items-center gap-2 font-semibold"><CalendarDays aria-hidden className="size-4 text-accent-foreground" /> Daily P&L</h2>
        <div className="flex items-center gap-1">
          <Button size="icon" variant="ghost" className="size-9" aria-label="Previous report month" disabled={month <= range.from.slice(0, 7)} onClick={() => setMonth(stepMonth(month, -1))}><ChevronLeft aria-hidden /></Button>
          <span className="min-w-24 text-center text-xs font-medium tabular-nums" aria-live="polite">{monthName.format(start)}</span>
          <Button size="icon" variant="ghost" className="size-9" aria-label="Next report month" disabled={month >= range.to.slice(0, 7)} onClick={() => setMonth(next)}><ChevronRight aria-hidden /></Button>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-7 gap-1.5 text-center">
        {weekdayLabels.map((day) => <div key={day} className="pb-1 text-xs text-muted-foreground">{day}</div>)}
        {Array.from({ length: leading }, (_, index) => <span key={`empty-${index}`} />)}
        {Array.from({ length: count }, (_, index) => {
          const day = index + 1;
          const date = `${month}-${String(day).padStart(2, "0")}`;
          const entry = byDate.get(date);
          const tone = entry?.netPaise ? (entry.netPaise > 0 ? "bg-positive/12 text-positive" : "bg-negative/12 text-negative") : "bg-surface-raised text-muted-foreground";
          return <button type="button" key={date} disabled={!entry} aria-pressed={selected === date}
            aria-label={entry ? `${formatSnapshotDate(date)}, ${entry.trades} closed trades, ${formatInr(entry.netPaise / 100, true)} net realized` : `${formatSnapshotDate(date)}, outside selected period`}
            className={cn("h-9 min-w-0 rounded-md border border-transparent text-sm font-medium tabular-nums outline-offset-0 hover:border-primary/55 disabled:bg-transparent disabled:opacity-40", tone,
              selected === date && "border-primary bg-primary/15 text-accent-foreground")}
            onClick={() => onSelect(selected === date ? null : date)}>{day}</button>;
        })}
      </div>
      {selectedEntry ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3 text-xs">
          <p><strong>{formatSnapshotDate(selectedEntry.date)}</strong> · {selectedEntry.trades} closed · {formatInr(selectedEntry.netPaise / 100, true)}</p>
          <Button variant="ghost" size="sm" onClick={() => onSelect(null)}>Clear day</Button>
        </div>
      ) : <p className="mt-4 text-xs text-muted-foreground">Select a day to filter the journal. Amounts are net realized P&L.</p>}
    </Card>
  );
}
