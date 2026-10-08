import { RunDetail } from "@/components/rca/run-detail";

export const metadata = { title: "Diagnosis details · K8s Hub" };

interface Props {
  params: Promise<{ runId: string }>;
}

export default async function RcaDetailPage({ params }: Props) {
  const { runId } = await params;
  // Keyed by id: going from one run to another starts with a fresh selection.
  return <RunDetail key={runId} id={runId} />;
}
