"use client";

import { useState } from "react";
import { RefreshCw, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { previewScenarios, type PreviewScenario } from "@/lib/api/mock";

export function PreviewControls({ scenario, loading, onScenario, onRefresh }: {
  scenario: PreviewScenario;
  loading: boolean;
  onScenario: (scenario: PreviewScenario) => void;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(scenario);

  return (
    <>
      <Button variant="outline" size="icon" onClick={onRefresh} disabled={loading} aria-label="Refresh sample data" title="Refresh sample data">
        <RefreshCw aria-hidden className={loading ? "motion-safe:animate-spin" : undefined} />
      </Button>
      <Dialog open={open} onOpenChange={(nextOpen) => {
        if (nextOpen) setSelected(scenario);
        setOpen(nextOpen);
      }}>
        <DialogTrigger asChild>
          <Button variant="outline"><SlidersHorizontal aria-hidden /> Preview data</Button>
        </DialogTrigger>
        <DialogContent>
          <DialogTitle>Preview data</DialogTitle>
          <DialogDescription>Choose a mock response to inspect how the dashboard loads and displays data.</DialogDescription>
          <form className="mt-5" onSubmit={(event) => {
            event.preventDefault();
            onScenario(selected);
            setOpen(false);
          }}>
            <fieldset className="space-y-2">
              <legend className="sr-only">Mock response</legend>
              {previewScenarios.map(({ value, label }) => (
                <label key={value} className="flex cursor-pointer items-center gap-3 rounded-lg border border-border p-3 text-sm has-checked:border-primary/60 has-checked:bg-primary/8">
                  <input
                    type="radio"
                    name="scenario"
                    value={value}
                    checked={selected === value}
                    onChange={() => setSelected(value)}
                    className="size-4 accent-primary"
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            <Button type="submit" className="mt-5 w-full">Apply preview</Button>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
