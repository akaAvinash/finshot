import type { Metadata } from "next";
import { Brokers } from "@/components/brokers/brokers";
import { requirePreviewSession } from "@/lib/preview-auth/session";

export const metadata: Metadata = { title: "Brokers" };

export default async function BrokersPage() {
  await requirePreviewSession();
  return <Brokers />;
}
