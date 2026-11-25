"use client";

import { useMemo, useRef, useState } from "react";
import { Activity, BookOpen, CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { PortfolioChart } from "@/components/dashboard/portfolio-chart";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Status } from "@/components/ui/status";
import { Table, TableCell, TableHead } from "@/components/ui/table";
import type { ReportDay, ReportTrade } from "@/lib/api/paper-report-types";
import type { PortfolioPoint } from "@/lib/api/types";
import { formatInr, formatSnapshotDate } from "@/lib/format";
import { fillReason, formatReportTime } from "@/lib/paper-reporting";
import { cn } from "@/lib/utils";

const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const monthName = new Intl.DateTimeFormat("en-IN", { month: "long", year: "numeric", timeZone: "UTC" });
const axisValue = (value: number) => formatInr(value);
const pageSize = 8;
const fillCount = (count: number) => `${count} ${count === 1 ? "fill" : "fills"}`;

function ReportCalendar({ days, selected, onSelect }: {
  days: ReportDay[];
  selected: string | null;
  onSelect: (date: string | null) => void;
}) {
  const months = [...new Set(days.map(({ date }) => date.slice(0, 7)))];
  const [activeMonth, setActiveMonth] = useState<string | null>(null);
  const selectedDayButton = useRef<HTMLButtonElement>(null);
  const chosenMonth = activeMonth ? months.indexOf(activeMonth) : -1;
  const monthIndex = chosenMonth >= 0 ? chosenMonth : months.length - 1;
  const month = months[monthIndex];
  const byDate = new Map(days.map((day) => [day.date, day]));
  const selectedDay = selected ? byDate.get(selected) : undefined;
  const first = new Date(`${month}-01T00:00:00Z`);
  const last = new Date(first);
  last.setUTCMonth(last.getUTCMonth() + 1, 0);

  function changeMonth(step: number) {
    setActiveMonth(months[monthIndex + step]);
    onSelect(null);
  }

  return <Card aria-labelledby="report-calendar" className="min-w-0 p-4 sm:p-5">
    <div className="flex flex-wrap items-center justify-between gap-1">
      <h2 id="report-calendar" className="flex items-center gap-2 font-semibold"><CalendarDays aria-hidden className="size-4 text-accent-foreground" /> Daily P&L</h2>
      {month && <div className="flex items-center gap-1">
        <Button size="icon" variant="ghost" className="size-9" aria-label="Previous report month" disabled={monthIndex === 0} onClick={() => changeMonth(-1)}><ChevronLeft aria-hidden /></Button>
        <span aria-live="polite" className="text-xs font-medium">{monthName.format(first)}</span>
        <Button size="icon" variant="ghost" className="size-9" aria-label="Next report month" disabled={monthIndex === months.length - 1} onClick={() => changeMonth(1)}><ChevronRight aria-hidden /></Button>
      </div>}
    </div>
    {month ? <>
      <div className="mt-3 grid grid-cols-7 gap-1 text-center">
        {weekdays.map((day) => <span key={day} className="mb-1 text-xs text-muted-foreground">{day}</span>)}
        {Array.from({ length: (first.getUTCDay() + 6) % 7 }, (_, index) => <span key={`gap-${index}`} />)}
        {Array.from({ length: last.getUTCDate() }, (_, index) => {
          const number = index + 1;
          const date = `${month}-${String(number).padStart(2, "0")}`;
          const entry = byDate.get(date);
          return <button key={date} type="button" disabled={!entry} aria-pressed={selected === date}
            ref={selected === date ? selectedDayButton : undefined}
            aria-label={entry ? `${formatSnapshotDate(date)}, ${fillCount(entry.fills)}, ${formatInr(entry.realisedPaise / 100, true)} realised` : formatSnapshotDate(date)}
            className={cn("min-h-9 rounded-md border border-transparent text-sm tabular-nums hover:border-primary/60 disabled:opacity-40",
              entry && "bg-surface-raised", entry && entry.realisedPaise > 0 && "bg-positive/12 text-positive",
              entry && entry.realisedPaise < 0 && "bg-negative/12 text-negative", selected === date && "border-primary")}
            onClick={() => onSelect(selected === date ? null : date)}>{number}</button>;
        })}
      </div>
      <div className="mt-3 flex min-h-9 flex-wrap items-center justify-between gap-1 border-t border-border pt-2 text-xs text-muted-foreground">
        {selectedDay ? <>
          <p>{formatSnapshotDate(selectedDay.date)} · {fillCount(selectedDay.fills)} · {formatInr(selectedDay.realisedPaise / 100, true)}</p>
          <Button variant="ghost" size="sm" onClick={() => {
            selectedDayButton.current?.focus();
            onSelect(null);
          }}>Clear day</Button>
        </> : <p>Select a day with fills to filter the journal.</p>}
      </div>
    </> : <p className="mt-3 text-sm text-muted-foreground">No daily activity in this period.</p>}
  </Card>;
}

function ReportTrend({ days }: { days: ReportDay[] }) {
  const points = useMemo(() => {
    const series: PortfolioPoint[] = [];
    let total = 0;
    for (const { date, realisedPaise } of days) {
      total += realisedPaise;
      series.push({ date, value: total / 100 });
    }
    return series;
  }, [days]);

  return <Card className="min-w-0 overflow-hidden" aria-labelledby="report-trend">
    <header className="border-b border-border p-4 sm:px-5">
      <h2 id="report-trend" className="flex items-center gap-2 font-semibold"><Activity aria-hidden className="size-4 text-accent-foreground" /> Realised P&L trend</h2>
      <p className="mt-1 text-xs text-muted-foreground">Cumulative realised P&L across the selected period.</p>
    </header>
    {points.length > 0 ? <div className="relative mx-3 my-3 h-58 sm:mx-4 sm:h-72">
      <PortfolioChart points={points} label="Paper realised P&L chart" formatValue={axisValue} />
    </div> : <p className="p-5 text-sm text-muted-foreground">No fills to chart in this period.</p>}
  </Card>;
}

function ReportJournal({ journal, truncated, day }: { journal: ReportTrade[]; truncated: boolean; day: string | null }) {
  const [page, setPage] = useState(0);
  const fills = day ? journal.filter((row) => row.date === day) : journal;
  const pages = Math.ceil(fills.length / pageSize);
  const visible = fills.slice(page * pageSize, (page + 1) * pageSize);

  return <Card className="min-w-0 overflow-hidden" aria-labelledby="trade-journal">
    <header className="border-b border-border p-4 sm:px-5">
      <h2 id="trade-journal" className="flex items-center gap-2 font-semibold"><BookOpen aria-hidden className="size-4 text-accent-foreground" /> Trade journal</h2>
      <p className="mt-1 text-xs text-muted-foreground">{fillCount(fills.length)} · {day ? formatSnapshotDate(day) : "Selected period"} · Times in IST</p>
      {truncated && <p className="mt-2 text-xs text-accent-foreground">The journal lists the latest 500 fills for the period. Export the CSV to download all fills.</p>}
    </header>
    {visible.length > 0 ? <div className="overflow-x-auto" role="region" aria-label="Trade journal table" tabIndex={0}>
      <Table>
        <caption className="sr-only">Paper fills ordered by latest fill</caption>
        <thead className="border-b border-border bg-surface-raised/60"><tr>
          <TableHead>Filled at</TableHead><TableHead>Instrument</TableHead><TableHead>Side</TableHead><TableHead>Strategy</TableHead>
          <TableHead className="text-right">Qty</TableHead><TableHead className="text-right">Fill price</TableHead><TableHead className="text-right">Fees</TableHead>
          <TableHead className="text-right">Realised P&L</TableHead><TableHead>Reason</TableHead>
        </tr></thead>
        <tbody>{visible.map((row) => <tr key={row.id} className="border-b border-border tabular-nums last:border-b-0">
          <TableCell><time dateTime={row.filledAt}>{formatSnapshotDate(row.date)}<span className="ml-2 text-xs text-muted-foreground">{formatReportTime(row.filledAt)}</span></time></TableCell>
          <TableCell className="font-medium">{row.instrument}</TableCell>
          <TableCell><Status tone={row.side === "Buy" ? "positive" : "neutral"}>{row.side}</Status></TableCell>
          <TableCell>{row.strategy ? `${row.strategy.name} · v${row.strategy.version}` : "Unattributed"}</TableCell>
          <TableCell className="text-right">{row.quantity}</TableCell>
          <TableCell className="text-right">{formatInr(row.fillPaise / 100)}</TableCell>
          <TableCell className="text-right">{formatInr(row.feesPaise / 100)}</TableCell>
          <TableCell className={cn("text-right font-semibold", row.pnlPaise > 0 && "text-positive", row.pnlPaise < 0 && "text-negative")}>
            {formatInr(row.pnlPaise / 100, true)}
          </TableCell>
          <TableCell>{fillReason[row.reason]}</TableCell>
        </tr>)}</tbody>
      </Table>
    </div> : <p className="p-5 text-sm text-muted-foreground">No fills to show in this journal view.</p>}
    {pages > 1 && <footer className="flex items-center justify-between gap-2 border-t border-border px-4 py-2 sm:px-5">
      <span className="text-xs text-muted-foreground" aria-live="polite">Page {page + 1} of {pages}</span>
      <div className="flex gap-1">
        <Button variant="ghost" size="icon" disabled={page === 0} aria-label="Previous trade page" onClick={() => setPage(page - 1)}><ChevronLeft aria-hidden /></Button>
        <Button variant="ghost" size="icon" disabled={page >= pages - 1} aria-label="Next trade page" onClick={() => setPage(page + 1)}><ChevronRight aria-hidden /></Button>
      </div>
    </footer>}
  </Card>;
}

export function ReportActivity({ days, journal, truncated }: { days: ReportDay[]; journal: ReportTrade[]; truncated: boolean }) {
  const [day, setDay] = useState<string | null>(null);

  return <>
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_22rem]">
      <ReportTrend days={days} />
      <ReportCalendar days={days} selected={day} onSelect={setDay} />
    </div>
    <ReportJournal key={day ?? "all"} journal={journal} day={day} truncated={truncated} />
  </>;
}

export function RetryReport() {
  return <Button variant="outline" onClick={() => window.location.reload()}>Retry report</Button>;
}
