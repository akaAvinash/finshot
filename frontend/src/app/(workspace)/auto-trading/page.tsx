import type { Metadata } from "next";
import { AutoTrading } from "@/components/auto-trading/auto-trading";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Auto Trading" };

export default async function AutoTradingPage() {
  await requirePreviewSession();
  return <AutoTrading />;
}
