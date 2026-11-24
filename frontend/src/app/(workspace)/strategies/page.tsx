import type { Metadata } from "next";
import { Strategies } from "@/components/strategies/strategies";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Strategies" };

export default async function StrategiesPage() {
  await requirePreviewSession();
  return <Strategies />;
}
