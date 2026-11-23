import type { Metadata } from "next";
import { Markets } from "@/components/markets/markets";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Markets" };

export default async function MarketsPage() {
  await requirePreviewSession();
  return <Markets />;
}
