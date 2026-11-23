"use client";

import { useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { marketChartScenarios, type MarketChartScenario } from "@/lib/api/market-mock";

export function MarketPreviewControls({ scenario, onApply }: { scenario: MarketChartScenario; onApply: (scenario: MarketChartScenario) => void }) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(scenario);

  return (
    <Dialog open={open} onOpenChange={(nextOpen) => {
      if (nextOpen) setSelected(scenario);
      setOpen(nextOpen);
    }}>
      <DialogTrigger asChild>
        <Button variant="outline" size="icon" aria-label="Chart demo data" title="Chart demo data">
          <SlidersHorizontal aria-hidden />
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogTitle>Chart demo data</DialogTitle>
        <DialogDescription>Choose the mock response for the candlestick chart.</DialogDescription>
        <form className="mt-5" onSubmit={(event) => {
          event.preventDefault();
          onApply(selected);
          setOpen(false);
        }}>
          <fieldset className="space-y-2">
            <legend className="sr-only">Chart response</legend>
            {marketChartScenarios.map(({ value, label }) => (
              <label key={value} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3 text-sm has-checked:border-primary/60 has-checked:bg-primary/8">
                <input type="radio" name="chart-response" value={value} checked={selected === value}
                  onChange={() => setSelected(value)} className="size-4 accent-primary" />
                {label}
              </label>
            ))}
          </fieldset>
          <Button type="submit" className="mt-4 w-full">Apply chart response</Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
