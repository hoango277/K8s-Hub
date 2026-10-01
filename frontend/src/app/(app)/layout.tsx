import { AuthGate } from "@/components/layout/auth-gate";
import { Header } from "@/components/layout/header";
import { Sidebar } from "@/components/layout/sidebar";
import { ToastProvider } from "@/components/ui/toast";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      {/* One toast area for every page: a message survives client-side
          navigation, and actions anywhere (chat approvals, skills) can report. */}
      <ToastProvider>
        <div className="flex h-screen">
          <Sidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            <Header />
            <main className="flex-1 overflow-y-auto">{children}</main>
          </div>
        </div>
      </ToastProvider>
    </AuthGate>
  );
}
