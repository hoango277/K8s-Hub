// USE CASE: operate Kubernetes in natural language.
// A streaming chat panel that shows which tool the assistant calls at each step.

import { ChatPanel } from "@/components/chat/chat-panel";

export const metadata = { title: "Chat · K8s Hub" };

export default function ChatPage() {
  return <ChatPanel />;
}
