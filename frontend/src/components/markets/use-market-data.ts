"use client";

import { useEffect, useState } from "react";
import { createTradeoClient } from "@/lib/api/client";
import type { MarketChartScenario } from "@/lib/api/market-mock";
import type { Instrument, MarketCandles, MarketOverview, MarketTimeframe } from "@/lib/api/market-types";

type Result<T> = { status: "loading" } | { status: "error" } | { status: "ready"; data: T };
type MarketSnapshot = { instruments: Instrument[]; overview: MarketOverview };

export type ChartRequest = { instrumentId: string; timeframe: MarketTimeframe; scenario: MarketChartScenario };

export function useMarketSnapshot() {
  const [snapshot, setSnapshot] = useState<Result<MarketSnapshot>>({ status: "loading" });
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const options = { signal: controller.signal };
    const client = createTradeoClient();

    Promise.all([client.getInstruments(options), client.getMarketOverview(options)])
      .then(([{ instruments }, overview]) => {
        if (!options.signal.aborted) setSnapshot({ status: "ready", data: { instruments, overview } });
      })
      .catch(() => {
        if (!options.signal.aborted) setSnapshot({ status: "error" });
      });

    return () => controller.abort();
  }, [revision]);

  function retry() {
    setSnapshot({ status: "loading" });
    setRevision((current) => current + 1);
  }

  return { snapshot, retry };
}

export function useMarketCandles(request: ChartRequest): Result<MarketCandles> {
  const [settled, setSettled] = useState<{ request: ChartRequest; result: Result<MarketCandles> }>();

  useEffect(() => {
    const controller = new AbortController();
    const client = createTradeoClient({ marketChartScenario: request.scenario });

    client.getMarketCandles(request.instrumentId, request.timeframe, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) setSettled({ request, result: { status: "ready", data } });
      })
      .catch(() => {
        if (!controller.signal.aborted) setSettled({ request, result: { status: "error" } });
      });

    return () => controller.abort();
  }, [request]);

  return settled?.request === request ? settled.result : { status: "loading" };
}
