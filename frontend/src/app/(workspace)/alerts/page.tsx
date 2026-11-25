import type { Metadata } from "next";
import { Alerts } from "@/components/alerts/alerts";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Alerts" };

export default async function AlertsPage() {
  await requirePreviewSession();
  return <Alerts />;
}
