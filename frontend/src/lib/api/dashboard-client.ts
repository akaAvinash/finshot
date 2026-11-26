import { parsePaperReportResult } from "./paper-report-response";
import type { PaperReport } from "./paper-report-types";

export type DashboardPaperData<T> =
  | { status: "ready"; data: T }
  | { status: "empty" | "unauthenticated" | "error" };

export type PaperEquity = { asOf: string; equityPaise: number };

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

async function read<T>(path: string, parse: (value: unknown) => DashboardPaperData<T> | undefined, signal: AbortSignal): Promise<DashboardPaperData<T>> {
  try {
    const response = await fetch(path, {
      headers: { Accept: "application/json" }, credentials: "same-origin", cache: "no-store", redirect: "error", signal,
    });
    if (response.status === 401) return { status: "unauthenticated" };
    if (response.ok) return parse(await response.json()) ?? { status: "error" };
  } catch {
    return { status: "error" };
  }
  return { status: "error" };
}

export function getDashboardReport(signal: AbortSignal) {
  return read<PaperReport>("/api/v1/reports/paper", parsePaperReportResult, signal);
}

export function getDashboardEquity(signal: AbortSignal) {
  return read<PaperEquity>("/api/v1/auto-trading/paper", (value) => {
    if (!object(value)) return;
    if (value.status === "empty") return { status: "empty" };
    if (value.status !== "ready" || !object(value.data)) return;
    const { asOf, account, source, environment } = value.data;
    if (source !== "demo" || environment !== "PAPER" || typeof asOf !== "string" || !Number.isFinite(Date.parse(asOf))
      || !object(account) || typeof account.equityPaise !== "number" || !Number.isSafeInteger(account.equityPaise) || account.equityPaise < 0) return;
    return { status: "ready", data: { asOf, equityPaise: account.equityPaise } };
  }, signal);
}
