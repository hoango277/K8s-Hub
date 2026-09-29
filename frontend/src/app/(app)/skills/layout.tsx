import { ToastProvider } from "@/components/ui/toast";

/** Shared by the list and detail pages so a toast survives navigating between
 * them (e.g. "Deleted X" after the detail page returns to the list). */
export default function SkillsLayout({ children }: { children: React.ReactNode }) {
  return <ToastProvider>{children}</ToastProvider>;
}
