import { DashboardSkeleton } from "@/components/data-state";
import { PageHeading } from "@/components/page-heading";

export default function LoadingDashboard() {
  return (
    <div className="space-y-5">
      <PageHeading title="Trading overview" description="Portfolio performance and Indian market activity in a simulated workspace." />
      <DashboardSkeleton />
    </div>
  );
}
