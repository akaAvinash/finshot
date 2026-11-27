"use client";

import { useEffect, useState } from "react";
import { marketDataClient, type MarketMode } from "@/lib/api/market-client";
import type { MarketChartScenario } from "@/lib/api/market-mock";
import type { Instrument, MarketCandles, MarketOverview, MarketSource, MarketTimeframe } from "@/lib/api/market-types";

type Result<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };
export type MarketSnapshot = { instruments: Instrument[]; catalogSource: MarketSource; overview: MarketOverview };

export type ChartRequest = { instrumentId: string; timeframe: MarketTimeframe; scenario: MarketChartScenario };

export function useMarketSnapshot(mode: MarketMode) {
  const [snapshot, setSnapshot] = useState<Result<MarketSnapshot>>({ status: "loading" });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    const client = marketDataClient(mode);

    Promise.all([client.getInstruments(options), client.getMarketOverview(options)])
      .then(([{ instruments, source }, overview]) => {
        if (!options.signal.aborted) setSnapshot({ status: "ready", data: { instruments, catalogSource: source, overview } });
      })
      .catch(() => {
        if (!options.signal.aborted) setSnapshot({ status: "error" });
      });

    return () => controller.abort();
  }, [mode, revision]);

  function retry() {
    setSnapshot({ status: "loading" });
    setRevision((current) => current + 1);
  }

  return { snapshot, retry };
}

export function useMarketCandles(request: ChartRequest, mode: MarketMode, instrumentId: string): Result<MarketCandles> {
  const [settled, setSettled] = useState<{ request: ChartRequest; instrumentId: string; result: Result<MarketCandles> }>();

  useEffect(() => {
    const controller = new AbortController();
    const client = marketDataClient(mode, request.scenario);

    client.getMarketCandles(instrumentId, request.timeframe, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setSettled({ request, instrumentId, result: { status: "ready", data } });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSettled({ request, instrumentId, result: { status: "error" } });
      });

    return () => controller.abort();
  }, [instrumentId, mode, request]);

  return settled?.request === request && settled.instrumentId === instrumentId ? settled.result : { status: "loading" };
}
