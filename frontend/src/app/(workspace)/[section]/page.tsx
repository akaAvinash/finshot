import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DataState } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";
import { Status } from "@/components/ui/status";
import { sections } from "@/lib/navigation";
import { requirePreviewSession } from "@/lib/preview-auth/session";

type SectionProps = { params: Promise<{ section: string }> };

function getSection(slug: string) {
  return sections.find((section) => section.slug === slug);
}

export async function generateMetadata({ params }: SectionProps): Promise<Metadata> {
  const section = getSection((await params).section);
  return { title: section?.title ?? "Page unavailable" };
}

export default async function SectionPage({ params }: SectionProps) {
  await requirePreviewSession();
  const section = getSection((await params).section);
  if (!section) notFound();

  return (
    <div className="space-y-6">
      <PageHeading title={section.title} description={section.description} actions={<Status tone="neutral">Placeholder</Status>} />
      <DataState title={`${section.title} preview`} description={section.empty} icon={section.icon} />
    </div>
  );
}
