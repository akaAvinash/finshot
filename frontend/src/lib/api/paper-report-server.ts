import "server-only";

import { authCookieHeader, sessionCookie } from "@/lib/auth/upstream";
import { reportCsvPath, reportQuery } from "@/lib/paper-reporting";
import type { PaperReportResult, ReportPeriod } from "./paper-report-types";
import { parsePaperReportResult } from "./paper-report-response";

export type PaperReportResponse = PaperReportResult | { status: "unauthenticated" | "invalid" | "unavailable" };

export function requestPaperReport(upstream: string, token: string, period: ReportPeriod, csv = false, requestId?: string) {
  const path = csv ? reportCsvPath : "/api/v1/reports/paper";
  return fetch(`${upstream}${path}${reportQuery(period)}`, {
    headers: {
      Accept: csv ? "text/csv" : "application/json",
      Cookie: authCookieHeader((name) => name === sessionCookie ? token : undefined),
      ...(requestId ? { "X-Request-ID": requestId } : {}),
    },
    cache: "no-store",
    redirect: "error",
    signal: AbortSignal.timeout(10000),
  });
}

export async function readPaperReport(upstream: string, token: string, period: ReportPeriod): Promise<PaperReportResponse> {
  try {
    const response = await requestPaperReport(upstream, token, period);
    if (!response.ok) {
      await response.body?.cancel();
      if (response.status === 401) return { status: "unauthenticated" };
      if (response.status === 400) return { status: "invalid" };
      return { status: "unavailable" };
    }

    return parsePaperReportResult(await response.json()) ?? { status: "unavailable" };
  } catch {
    return { status: "unavailable" };
  }
}
