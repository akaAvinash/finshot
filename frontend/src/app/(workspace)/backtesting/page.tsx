import type { Metadata } from "next";
import { Backtesting } from "@/components/backtesting/backtesting";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Backtesting" };

export default async function BacktestingPage() {
  const { mode } = await requireWorkspaceSession();
  return <Backtesting mode={mode} />;
}
