import type { Metadata } from "next";
import { Dashboard } from "@/components/dashboard/dashboard";
import { requireWorkspaceSession } from "@/lib/auth/workspace-session";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  await requireWorkspaceSession();
  return <Dashboard />;
}
