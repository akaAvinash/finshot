import type { BacktestConfig, BacktestPoint, BacktestResult, BacktestRun, BacktestTrade } from "./api/backtest-types";
import type { MarketCandle } from "./api/market-types";

export const basisPoints = 10_000;
export const minCapitalPaise = 100_000;
export const maxCapitalPaise = 1_000_000_000;
export const maxCostBps = 500;
const lookback = 3;

export class BacktestInputError extends Error {}

function isCalendarDate(value: string) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().startsWith(value);
}

export function validateBacktestConfig(config: BacktestConfig, range: { from: string; to: string }) {
  if (![config.from, config.to, config.outOfSampleFrom].every(isCalendarDate)) return "Enter valid dates for the run window and holdout.";
  if (config.from < range.from || config.to > range.to) return "Select a run window within the available demo history.";
  if (config.from >= config.outOfSampleFrom || config.outOfSampleFrom >= config.to) {
    return "The out-of-sample start must fall between the start and end dates.";
  }
  if (!Number.isInteger(config.capitalPaise) || config.capitalPaise < minCapitalPaise || config.capitalPaise > maxCapitalPaise) {
    return "Starting capital must be between ₹1,000 and ₹1,00,00,000.";
  }
  if (![config.feeBps, config.slippageBps].every((cost) => Number.isInteger(cost) && cost >= 0 && cost <= maxCostBps)) {
    return "Fees and slippage must be whole basis points between 0 and 500.";
  }
  return null;
}

type Position = { entryAt: string; quantity: number; entryPaise: number; feePaise: number };

function feeOn(grossPaise: number, rate: number) {
  return Math.ceil(grossPaise * rate / basisPoints);
}

export function replayDemoBacktest(config: BacktestConfig, candles: readonly MarketCandle[], positionSizeBps: number): BacktestResult {
  const bars = candles.filter(({ time }) => time.slice(0, 10) >= config.from && time.slice(0, 10) <= config.to);
  const holdout = bars.findIndex(({ time }) => time.slice(0, 10) >= config.outOfSampleFrom);
  if (holdout < lookback || bars.length - holdout < 2) {
    throw new BacktestInputError("Choose at least three warm-up sessions and two out-of-sample sessions.");
  }

  let cash = config.capitalPaise;
  let peak = cash;
  let position: Position | null = null;
  const trades: BacktestTrade[] = [];
  const points: BacktestPoint[] = [];

  for (let index = holdout; index < bars.length; index++) {
    const bar = bars[index];
    const previous = bars.slice(index - lookback, index);
    const lastClose = previous[lookback - 1].close;
    const movingAverage = previous.reduce((sum, candle) => sum + candle.close, 0) / lookback;
    const longSignal = lastClose > movingAverage;
    const lastSession = index === bars.length - 1;
    const openPaise = Math.round(bar.open * 100);

    if (position && (!longSignal || lastSession)) {
      const exitPaise = Math.floor(openPaise * (basisPoints - config.slippageBps) / basisPoints);
      const proceeds = exitPaise * position.quantity;
      const exitFee = feeOn(proceeds, config.feeBps);
      const feesPaise = position.feePaise + exitFee;
      cash += proceeds - exitFee;
      trades.push({
        id: `trade-${trades.length + 1}`,
        entryAt: position.entryAt,
        exitAt: bar.time,
        quantity: position.quantity,
        entryPaise: position.entryPaise,
        exitPaise,
        feesPaise,
        pnlPaise: proceeds - position.entryPaise * position.quantity - feesPaise,
      });
      position = null;
    } else if (!position && longSignal && !lastSession) {
      const entryPaise = Math.ceil(openPaise * (basisPoints + config.slippageBps) / basisPoints);
      const budget = Math.floor(cash * positionSizeBps / basisPoints);
      const quantity = Math.floor(budget * basisPoints / (entryPaise * (basisPoints + config.feeBps)));
      if (quantity > 0) {
        const gross = entryPaise * quantity;
        const feePaise = feeOn(gross, config.feeBps);
        cash -= gross + feePaise;
        position = { entryAt: bar.time, quantity, entryPaise, feePaise };
      }
    }

    const equityPaise = cash + (position ? Math.round(bar.close * 100) * position.quantity : 0);
    peak = Math.max(peak, equityPaise);
    const drawdownBps = -Math.round((peak - equityPaise) * basisPoints / peak) || 0;
    points.push({ date: bar.time.slice(0, 10), equityPaise, drawdownBps });
  }

  const netPnlPaise = cash - config.capitalPaise;
  return {
    endingEquityPaise: cash,
    netPnlPaise,
    returnBps: Math.round(netPnlPaise * basisPoints / config.capitalPaise),
    maxDrawdownBps: Math.min(...points.map(({ drawdownBps }) => drawdownBps)),
    winRateBps: trades.length ? Math.round(trades.filter(({ pnlPaise }) => pnlPaise > 0).length * basisPoints / trades.length) : null,
    totalFeesPaise: trades.reduce((total, trade) => total + trade.feesPaise, 0),
    points,
    trades,
  };
}

const tradeTime = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata", day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});

export function formatBacktestTime(value: string) {
  return `${tradeTime.format(new Date(value))} IST`;
}

export function backtestTradesCsv(run: Extract<BacktestRun, { status: "completed" }>) {
  const header = "environment,run_id,instrument_id,entry_utc,exit_utc,quantity,entry_inr,exit_inr,fees_inr,pnl_inr";
  const inr = (paise: number) => (paise / 100).toFixed(2);
  const rows = run.result.trades.map((trade) => [
    run.environment, run.id, run.config.instrumentId, trade.entryAt, trade.exitAt, trade.quantity,
    inr(trade.entryPaise), inr(trade.exitPaise), inr(trade.feesPaise), inr(trade.pnlPaise),
  ].join(","));
  return `${[header, ...rows].join("\r\n")}\r\n`;
}
