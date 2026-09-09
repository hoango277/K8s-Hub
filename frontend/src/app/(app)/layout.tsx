// Shell chung cho khu vuc dang nhap: sidebar + header.
// TODO: ghep Sidebar / Header, guard auth.

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <div className="flex h-screen">{children}</div>;
}
