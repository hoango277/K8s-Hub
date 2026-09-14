"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ClipboardCheck,
  MessagesSquare,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Stethoscope,
  Telescope,
  Wrench,
  type LucideIcon,
} from "lucide-react";

import { useLuuTru } from "@/hooks/use-luu-tru";
import { cn } from "@/lib/utils";

interface Muc {
  href: string;
  nhan: string;
  icon: LucideIcon;
}

const MUC: Muc[] = [
  { href: "/chat", nhan: "Trò chuyện", icon: MessagesSquare },
  { href: "/rca", nhan: "Chẩn đoán", icon: Stethoscope },
  { href: "/skills", nhan: "Kỹ năng", icon: Wrench },
  { href: "/approvals", nhan: "Chờ duyệt", icon: ClipboardCheck },
  { href: "/observability", nhan: "Giám sát AI", icon: Telescope },
  { href: "/settings", nhan: "Cấu hình", icon: Settings },
];

const KHOA_THU_GON = "k8shub.nav";

export function Sidebar() {
  const duongDan = usePathname();

  const [daLuu, luuThuGon] = useLuuTru(KHOA_THU_GON);
  const thuGon = daLuu === "1";

  function doiTrangThai() {
    luuThuGon(thuGon ? "0" : "1");
  }

  return (
    <aside
      className={cn(
        "flex shrink-0 flex-col border-r transition-[width] duration-200 ease-out",
        thuGon ? "w-14" : "w-56",
      )}
    >
      <div
        className={cn(
          "flex items-center gap-1 px-2 py-3",
          thuGon && "justify-center",
        )}
      >
        {!thuGon && (
          <span className="flex-1 truncate px-2 text-sm font-semibold">K8s Hub</span>
        )}

        <button
          type="button"
          onClick={doiTrangThai}
          aria-expanded={!thuGon}
          aria-label={thuGon ? "Mở rộng thanh điều hướng" : "Thu gọn thanh điều hướng"}
          title={thuGon ? "Mở rộng" : "Thu gọn"}
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg transition",
            "text-[var(--muted-foreground)] hover:bg-[var(--accent)] hover:text-[var(--foreground)]",
          )}
        >
          {thuGon ? (
            <PanelLeftOpen aria-hidden className="size-4" />
          ) : (
            <PanelLeftClose aria-hidden className="size-4" />
          )}
        </button>
      </div>

      <nav className="flex flex-col gap-0.5 px-2">
        {MUC.map((m) => {
          const dangChon = duongDan === m.href || duongDan.startsWith(`${m.href}/`);
          const Icon = m.icon;

          return (
            <Link
              key={m.href}
              href={m.href}
              // Thu gọn rồi thì chữ biến mất, chỉ còn icon — `title` là thứ duy
              // nhất còn lại để biết nút nào là nút nào.
              title={thuGon ? m.nhan : undefined}
              aria-current={dangChon ? "page" : undefined}
              className={cn(
                "relative flex h-9 items-center gap-2.5 rounded-lg text-sm transition",
                thuGon ? "justify-center px-0" : "px-2.5",
                dangChon
                  ? "bg-[var(--accent)] font-medium text-[var(--accent-foreground)]"
                  : "text-[var(--muted-foreground)] hover:bg-[var(--accent)]/60 hover:text-[var(--foreground)]",
              )}
            >
              {/* Vạch đánh dấu mục đang mở. Lúc thu gọn, nền xám nhạt không đủ
                  rõ trên một ô vuông nhỏ, nên cần thêm dấu này. */}
              {dangChon && (
                <span
                  aria-hidden
                  className="absolute left-0 h-5 w-0.5 rounded-r bg-[var(--primary)]"
                />
              )}
              <Icon aria-hidden className="size-4 shrink-0" />
              {!thuGon && <span className="truncate">{m.nhan}</span>}
            </Link>
          );
        })}
      </nav>
    </aside>
  );
}
