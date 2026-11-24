import type { Metadata } from "next";
import { Reports } from "@/components/reports/reports";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Reports" };

export default async function ReportsPage() {
  await requirePreviewSession();
  return <Reports />;
}
