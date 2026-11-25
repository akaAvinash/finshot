"use client";

import { useState } from "react";
import Link from "next/link";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ReportPeriod } from "@/lib/api/paper-report-types";
import { reportCsvFilename, reportCsvPath, reportQuery } from "@/lib/paper-reporting";

export function ReportExport({ period }: { period: ReportPeriod }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<"expired" | "failed" | null>(null);

  async function exportTrades() {
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`${reportCsvPath}${reportQuery(period)}`, { cache: "no-store" });
      if (!response.ok) {
        setError(response.status === 401 ? "expired" : "failed");
        return;
      }

      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = reportCsvFilename;
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setError("failed");
    } finally {
      setPending(false);
    }
  }

  return <div className="w-full space-y-2 sm:w-auto">
    <Button aria-disabled={pending} onClick={() => { if (!pending) void exportTrades(); }} className="h-11 w-full sm:w-auto">
      <Download aria-hidden /> {pending ? "Preparing CSV…" : "Export period CSV"}
    </Button>
    {error && <p role="alert" className="text-xs text-negative">
      {error === "expired" ? <Link href="/login" className="underline">Sign in again to export trades.</Link> : "CSV export failed. Try again."}
    </p>}
  </div>;
}
