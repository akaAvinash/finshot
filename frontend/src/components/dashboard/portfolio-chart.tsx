"use client";

import { useEffect, useRef } from "react";
import { AreaSeries, ColorType, createChart, CrosshairMode, TrackingModeExitMode } from "lightweight-charts";
import { useTheme } from "next-themes";
import type { PortfolioPoint } from "@/lib/api/types";

const axisFormatter = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });
const formatAmount = (value: number) => `₹${axisFormatter.format(value)}`;

export function PortfolioChart({ points, label = "Sample portfolio chart", formatValue = formatAmount, tone = "gold" }: {
  points: readonly PortfolioPoint[];
  label?: string;
  formatValue?: (value: number) => string;
  tone?: "gold" | "negative";
}) {
  const host = useRef<HTMLDivElement>(null);
  const { resolvedTheme } = useTheme();

  useEffect(() => {
    if (!host.current) return;

    const tokens = getComputedStyle(host.current);
    const color = (name: string) => tokens.getPropertyValue(name).trim();
    const grid = color("--border");
    const chart = createChart(host.current, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: color("--muted-foreground"),
        fontFamily: "Geist Variable, Segoe UI, sans-serif",
        fontSize: 11,
      },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.13, bottom: 0.10 } },
      timeScale: { borderColor: grid, rightOffset: 0.8, fixLeftEdge: true },
      handleScroll: false,
      handleScale: false,
      localization: { locale: "en-IN" },
      trackingMode: { exitMode: TrackingModeExitMode.OnNextTap },
    });

    const series = chart.addSeries(AreaSeries, {
      lineColor: color(tone === "negative" ? "--negative" : "--chart-line"),
      topColor: tone === "negative" ? `${color("--negative")}35` : color("--chart-fill"),
      bottomColor: "transparent",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      priceFormat: { type: "custom", formatter: formatValue },
    });
    series.setData(points.map(({ date, value }) => ({ time: date, value })));
    chart.timeScale().fitContent();

    return () => chart.remove();
  }, [points, resolvedTheme, formatValue, tone]);

  return <div role="group" aria-label={label} ref={host} className="absolute inset-0" />;
}
