import type { Metadata } from "next";
import { Dashboard } from "@/components/dashboard/dashboard";
import { StagingDashboard } from "@/components/dashboard/staging-dashboard";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";
import { dashboardDate } from "@/lib/dashboard-ledger";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  const { mode } = await requireWorkspaceSession();
  return mode === "staging" ? <StagingDashboard today={dashboardDate(new Date())} /> : <Dashboard />;
}
