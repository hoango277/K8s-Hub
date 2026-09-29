import { SkillDetail } from "@/components/skills/skill-detail";

interface Props {
  params: Promise<{ name: string }>;
}

export async function generateMetadata({ params }: Props) {
  const { name } = await params;
  return { title: `${decodeURIComponent(name)} · Skills · K8s Hub` };
}

export default async function SkillDetailPage({ params }: Props) {
  const { name } = await params;
  // Keyed by name: moving between two skills starts from a fresh page state
  // (selected file, open dialogs) instead of carrying the last one over.
  const skill = decodeURIComponent(name);
  return <SkillDetail key={skill} name={skill} />;
}
