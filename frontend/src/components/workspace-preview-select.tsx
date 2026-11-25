import { useId } from "react";
import { Label } from "@/components/ui/input";
import type { WorkspaceScenario } from "@/lib/api/workspace-controls-types";

const scenarios = [
  { value: "ready", label: "Sample data" }, { value: "stale", label: "Stale data" }, { value: "empty", label: "Empty workspace" },
  { value: "denied", label: "Permission denied" }, { value: "error", label: "Request error" },
] as const;

export function WorkspacePreviewSelect({ label, scenario, disabled, onChange }: {
  label: string;
  scenario: WorkspaceScenario;
  disabled: boolean;
  onChange: (scenario: WorkspaceScenario) => void;
}) {
  const id = useId();
  return <>
    <Label htmlFor={id} className="sr-only">{label}</Label>
    <select id={id} className="h-11 rounded-lg border border-input bg-background px-3 text-sm" value={scenario} disabled={disabled}
      onChange={({ target }) => {
        const next = scenarios.find(({ value }) => value === target.value);
        if (next) onChange(next.value);
      }}>
      {scenarios.map(({ value, label }) => <option key={value} value={value}>{label}</option>)}
    </select>
  </>;
}
