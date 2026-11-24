import type { Metadata } from "next";
import { Backtesting } from "@/components/backtesting/backtesting";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Backtesting" };

export default async function BacktestingPage() {
  await requirePreviewSession();
  return <Backtesting />;
}
