import type { Metadata } from "next";
import { AutoTrading } from "@/components/auto-trading/auto-trading";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Auto Trading" };

export default async function AutoTradingPage() {
  const session = await requireWorkspaceSession();
  return <AutoTrading mode={session.mode} readOnlyLimits={session.mode === "staging" && session.tester} />;
}
