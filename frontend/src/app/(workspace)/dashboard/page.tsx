import type { Metadata } from "next";
import { Dashboard } from "@/components/dashboard/dashboard";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Dashboard" };

export default async function DashboardPage() {
  await requirePreviewSession();
  return <Dashboard />;
}
