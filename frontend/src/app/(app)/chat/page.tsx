// USE CASE: ra lệnh Kubernetes bằng ngôn ngữ tự nhiên.
// Khung chat streaming, hiện rõ trợ lý gọi công cụ nào ở từng bước.

import { ChatPanel } from "@/components/chat/chat-panel";

export const metadata = { title: "Trò chuyện · K8s Hub" };

export default function ChatPage() {
  return <ChatPanel />;
}
