import { DashboardSkeleton } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";

export default function LoadingReports() {
  return <div className="space-y-5">
    <PageHeading title="Reports" description="Paper trading performance, daily P&L and fill history." />
    <DashboardSkeleton label="Loading paper report" />
  </div>;
}
