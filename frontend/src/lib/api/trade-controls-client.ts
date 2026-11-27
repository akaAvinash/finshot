import { AuthError, writeAccount } from "@/lib/auth/browser-client";
import { isRecord, isTimestamp, stagingRequest } from "./staging-client";

export const tradeControlFields = [
  "lossLimitPaise", "tradeLimit", "profitLimitPaise", "maxConsecutiveLosses",
  "stopLossBps", "takeProfitBps", "maxRiskPerTradePaise", "maxPositionSizeBps",
] as const;
export type TradeControlField = (typeof tradeControlFields)[number];
type NullableField = "profitLimitPaise" | "stopLossBps" | "takeProfitBps";
export type TradeControlValues = Record<Exclude<TradeControlField, NullableField>, number> & Record<NullableField, number | null>;
export type TradeControlBound = { minimum: number; maximum: number; nullable: boolean };
export type TradeControlSettings = {
  environment: "PAPER"; revision: number; updatedAt: string | null;
  controls: TradeControlValues; defaults: TradeControlValues; bounds: Record<TradeControlField, TradeControlBound>;
};
export type TradeControlChange = {
  revision: number; changedAt: string; fields: { field: TradeControlField; from: number | null; to: number | null }[];
};

const path = "settings/trade-controls";
const nullableFields: readonly TradeControlField[] = ["profitLimitPaise", "stopLossBps", "takeProfitBps"];
const nonnegative = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const fieldId = (value: unknown): value is TradeControlField => tradeControlFields.some((field) => field === value);

function bound(value: unknown): value is TradeControlBound {
  return isRecord(value) && nonnegative(value.minimum) && nonnegative(value.maximum) &&
    value.maximum >= value.minimum && typeof value.nullable === "boolean";
}

function controlValues(value: unknown): value is TradeControlValues {
  return isRecord(value) && tradeControlFields.every((field) =>
    (nullableFields.includes(field) && value[field] === null) || nonnegative(value[field]));
}

function settings(value: unknown): TradeControlSettings | undefined {
  if (!isRecord(value) || value.environment !== "PAPER" || !nonnegative(value.revision) ||
      !(value.updatedAt === null || isTimestamp(value.updatedAt)) ||
      !controlValues(value.controls) || !controlValues(value.defaults)) return;
  const bounds = value.bounds;
  if (!hasBounds(bounds)) return;
  return { environment: "PAPER", revision: value.revision, updatedAt: value.updatedAt, controls: value.controls, defaults: value.defaults, bounds };
}

function hasBounds(value: unknown): value is Record<TradeControlField, TradeControlBound> {
  return isRecord(value) && tradeControlFields.every((field) => bound(value[field]));
}

function change(row: unknown): row is TradeControlChange {
  return isRecord(row) && nonnegative(row.revision) && isTimestamp(row.changedAt) && Array.isArray(row.fields) &&
    row.fields.every((entry) => isRecord(entry) && fieldId(entry.field) &&
      (entry.from === null || nonnegative(entry.from)) && (entry.to === null || nonnegative(entry.to)));
}

export const getTradeControlSettings = (signal?: AbortSignal) => stagingRequest(path, settings, signal);
export const getTradeControlHistory = (signal?: AbortSignal) => stagingRequest(`${path}/history`, (value) => {
  if (isRecord(value) && Array.isArray(value.changes) && value.changes.every(change)) return value.changes;
}, signal);

export async function saveTradeControlSettings(expectedRevision: number, controls: TradeControlValues, signal?: AbortSignal) {
  const response = await writeAccount(`/api/v1/${path}`, "PUT", { expectedRevision, controls }, signal);
  const saved = settings(await response.json().catch(() => undefined));
  if (!saved) throw new AuthError(502, "INVALID_RESPONSE", undefined, undefined, response.headers.get("X-Request-ID") ?? undefined);
  return saved;
}

export function tradeControlFieldErrors(error: AuthError) {
  const fields: Partial<Record<TradeControlField, TradeControlBound>> = {};
  if (error.code === "TRADE_CONTROLS_OUT_OF_BOUNDS" && Array.isArray(error.fieldErrors)) {
    for (const entry of error.fieldErrors) {
      if (isRecord(entry) && fieldId(entry.field) && bound(entry.bound)) fields[entry.field] = entry.bound;
    }
  }
  return fields;
}
