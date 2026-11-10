// USE CASE: operate Kubernetes in natural language.
// A streaming chat panel that shows which tool the assistant calls at each step.

import { Suspense } from "react";

import { ChatPanel } from "@/components/chat/chat-panel";
import { Spinner } from "@/components/ui/spinner";

export const metadata = { title: "Chat · K8s Hub" };

export default function ChatPage() {
  // ChatPanel reads `?thread=` with useSearchParams, which Next.js requires to sit
  // under a Suspense boundary (otherwise the build refuses to prerender the page).
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center gap-2 text-sm text-[var(--muted-foreground)]">
          <Spinner /> Loading chat…
        </div>
      }
    >
      <ChatPanel />
    </Suspense>
  );
}
