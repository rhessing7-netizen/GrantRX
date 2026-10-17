import type { Metadata } from "next";
import { PublicOpportunityView } from "@/components/PublicOpportunityView";

export const metadata: Metadata = {
  title: "Opportunity Details — EdFintia",
  description:
    "Read a verified summary of this education funding opportunity on EdFintia.",
};

export default async function ScholarshipDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <PublicOpportunityView id={id} />;
}
