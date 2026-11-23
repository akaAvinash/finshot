"use client";

import { DataState } from "@/components/data-state";
import { Button } from "@/components/ui/button";

export default function WorkspaceError({ reset }: { reset: () => void }) {
  return (
    <DataState
      error
      title="This page could not load"
      description="Try loading the workspace page again."
      action={<Button variant="outline" onClick={reset}>Try again</Button>}
    />
  );
}
