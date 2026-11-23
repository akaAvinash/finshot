"use client";

import { useEffect, useRef, useState } from "react";
import { CandlestickSeries, ColorType, createChart, CrosshairMode, HistogramSeries, TickMarkType, TrackingModeExitMode, type Time, type UTCTimestamp } from "lightweight-charts";
import type { MarketCandle, MarketTimeframe } from "@/lib/api/market-types";
import { formatInr, formatPrice } from "@/lib/format";
import { formatMarketTime, formatVolume } from "./market-format";

const timeZone = "Asia/Kolkata";
const tickTime = new Intl.DateTimeFormat("en-IN", { timeZone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
const tickDay = new Intl.DateTimeFormat("en-IN", { timeZone, day: "numeric" });
const tickMonth = new Intl.DateTimeFormat("en-IN", { timeZone, month: "short" });
const tickYear = new Intl.DateTimeFormat("en-IN", { timeZone, year: "numeric" });

function tickLabel(seconds: number, type: TickMarkType) {
  const date = new Date(seconds * 1000);
  if (type === TickMarkType.Year) return tickYear.format(date);
  if (type === TickMarkType.Month) return tickMonth.format(date);
  if (type === TickMarkType.DayOfMonth) return tickDay.format(date);
  return tickTime.format(date);
}

export function CandlestickChart({ candles, timeframe }: { candles: MarketCandle[]; timeframe: MarketTimeframe }) {
  const host = useRef<HTMLDivElement>(null);
  const [hovered, setHovered] = useState<MarketCandle>();
  const shown = hovered ?? candles.at(-1);

  useEffect(() => {
    const container = host.current;
    if (!container || !candles.length) return;

    const points = candles.map(({ time, ...bar }) => ({ ...bar, time: (Date.parse(time) / 1000) as UTCTimestamp }));
    const barByTime = new Map(points.map(({ time }, index) => [time, candles[index]]));
    const hasVolume = points.some(({ volume }) => volume !== null);

    const chart = createChart(container, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        background: { type: ColorType.Solid, color: "transparent" },
        fontFamily: "Geist Variable, Segoe UI, sans-serif",
        fontSize: 11,
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.11, bottom: hasVolume ? 0.24 : 0.1 } },
      timeScale: {
        rightOffset: 2,
        timeVisible: timeframe !== "1D",
        secondsVisible: false,
        tickMarkFormatter: (time: Time, type: TickMarkType) => typeof time === "number" ? tickLabel(time, type) : null,
      },
      handleScroll: { mouseWheel: false, vertTouchDrag: false },
      handleScale: { mouseWheel: false },
      trackingMode: { exitMode: TrackingModeExitMode.OnNextTap },
      localization: {
        locale: "en-IN",
        timeFormatter: (time: Time) => typeof time === "number" ? formatMarketTime(new Date(time * 1000).toISOString()) : String(time),
      },
    });

    const priceSeries = chart.addSeries(CandlestickSeries, {
      borderVisible: false,
      priceLineVisible: false,
      priceFormat: { type: "custom", formatter: (value: number) => `₹${formatPrice(value)}` },
    });
    priceSeries.setData(points.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })));

    const volumeSeries = hasVolume ? chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      priceLineVisible: false,
      lastValueVisible: false,
    }) : undefined;
    volumeSeries?.priceScale().applyOptions({ scaleMargins: { top: 0.79, bottom: 0 }, visible: false });

    const applyTheme = () => {
      const tokens = getComputedStyle(container);
      const color = (name: string) => tokens.getPropertyValue(name).trim();
      const positive = color("--positive");
      const negative = color("--negative");
      const grid = color("--border");

      chart.applyOptions({
        layout: { textColor: color("--muted-foreground") },
        grid: { vertLines: { color: grid }, horzLines: { color: grid } },
        timeScale: { borderColor: grid },
      });
      priceSeries.applyOptions({ upColor: positive, downColor: negative, wickUpColor: positive, wickDownColor: negative });
      volumeSeries?.setData(points.flatMap(({ time, open, close, volume }) => (
        volume === null ? [] : [{ time, value: volume, color: `${close >= open ? positive : negative}65` }]
      )));
    };

    applyTheme();
    const observer = new MutationObserver(applyTheme);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });

    const barsAcross = Math.max(28, Math.floor(container.clientWidth / 8));
    if (candles.length <= barsAcross) {
      chart.timeScale().fitContent();
    } else {
      chart.timeScale().setVisibleLogicalRange({ from: candles.length - barsAcross, to: candles.length + 1 });
    }

    chart.subscribeCrosshairMove(({ time }) => {
      setHovered(typeof time === "number" ? barByTime.get(time) : undefined);
    });

    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [candles, timeframe]);

  return (
    <>
      {shown && (
        <dl aria-label={hovered ? "Highlighted candle values" : "Latest candle values"} className="flex flex-wrap gap-x-3 gap-y-1 px-4 pt-3 text-xs tabular-nums sm:px-5">
          {[
            { label: "Open", short: "O", value: formatInr(shown.open) },
            { label: "High", short: "H", value: formatInr(shown.high) },
            { label: "Low", short: "L", value: formatInr(shown.low) },
            { label: "Close", short: "C", value: formatInr(shown.close) },
            ...(shown.volume === null ? [] : [{ label: "Volume", short: "Vol", value: formatVolume(shown.volume, true) }]),
          ].map(({ label, short, value }) => (
            <div key={label} className="flex gap-1">
              <dt className="text-muted-foreground" aria-label={label}>{short}</dt>
              <dd className="font-medium">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="relative mx-2.5 my-3 h-66 sm:mx-4 sm:h-76">
        <div role="group" aria-label={`Demo ${timeframe} candlestick chart`} ref={host} className="absolute inset-0" />
      </div>
    </>
  );
}
