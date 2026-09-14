"use client";

import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/**
 * Hiển thị câu trả lời của trợ lý dưới dạng markdown.
 *
 * AN TOÀN — phần quan trọng nhất của file này:
 *
 * Nội dung ở đây do MÔ HÌNH sinh ra, mà mô hình lại vừa đọc log và thông báo
 * lỗi lấy từ cụm Kubernetes. Nghĩa là một kẻ tấn công đặt được chuỗi lạ vào
 * log của pod thì chuỗi đó có đường đi thẳng tới trình duyệt người trực.
 *
 * Vì vậy TUYỆT ĐỐI không thêm `rehype-raw` hay `dangerouslySetInnerHTML`.
 * Mặc định react-markdown escape mọi thẻ HTML thô — `<script>` hiện ra thành
 * chữ chứ không chạy. Giữ nguyên như vậy.
 *
 * Liên kết cũng là thứ mô hình có thể bịa ra, nên mở ở tab mới kèm
 * `noopener noreferrer nofollow`, và để react-markdown lọc giao thức (chặn
 * `javascript:`).
 */

const KHOI = "my-2 first:mt-0 last:mb-0";

interface Props {
  children: string;
  className?: string;
}

function MarkdownGoc({ children, className }: Props) {
  return (
    <div className={cn("text-sm leading-relaxed", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          p: ({ children }) => <p className={KHOI}>{children}</p>,

          // Danh sách: dùng nhiều nhất, vì trợ lý hay liệt kê các bước kiểm tra.
          ul: ({ children }) => (
            <ul className={cn(KHOI, "list-disc space-y-1 pl-5")}>{children}</ul>
          ),
          ol: ({ children }) => (
            <ol className={cn(KHOI, "list-decimal space-y-1 pl-5")}>{children}</ol>
          ),
          li: ({ children }) => <li className="pl-0.5">{children}</li>,

          strong: ({ children }) => (
            <strong className="font-semibold">{children}</strong>
          ),
          em: ({ children }) => <em className="italic">{children}</em>,

          // Lệnh kubectl thường dài hơn bề ngang khung chat, nên khối mã phải
          // tự cuộn ngang. Không có nó thì cả trang bị đẩy rộng ra.
          pre: ({ children }) => (
            <pre
              className={cn(
                KHOI,
                "overflow-x-auto rounded-md bg-[var(--muted)] p-3 text-xs leading-relaxed",
                "[&_code]:bg-transparent [&_code]:p-0 [&_code]:text-xs",
              )}
            >
              {children}
            </pre>
          ),
          code: ({ children, ...props }) => (
            <code
              className="rounded bg-[var(--muted)] px-1 py-0.5 font-mono text-[0.85em]"
              {...props}
            >
              {children}
            </code>
          ),

          a: ({ children, href }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer nofollow"
              className="underline underline-offset-2 hover:opacity-80"
            >
              {children}
            </a>
          ),

          // Tiêu đề trong khung chat phải nhỏ thôi — đây là tin nhắn, không
          // phải một trang tài liệu.
          h1: ({ children }) => (
            <h3 className={cn(KHOI, "text-base font-semibold")}>{children}</h3>
          ),
          h2: ({ children }) => (
            <h3 className={cn(KHOI, "text-sm font-semibold")}>{children}</h3>
          ),
          h3: ({ children }) => (
            <h4 className={cn(KHOI, "text-sm font-semibold")}>{children}</h4>
          ),
          h4: ({ children }) => (
            <h4 className={cn(KHOI, "text-sm font-medium")}>{children}</h4>
          ),

          blockquote: ({ children }) => (
            <blockquote
              className={cn(KHOI, "border-l-2 pl-3 text-[var(--muted-foreground)]")}
            >
              {children}
            </blockquote>
          ),

          hr: () => <hr className="my-3" />,

          // Bảng cuộn trong khung riêng, không để nó kéo giãn cả trang.
          table: ({ children }) => (
            <div className={cn(KHOI, "overflow-x-auto")}>
              <table className="w-full border-collapse text-xs">{children}</table>
            </div>
          ),
          th: ({ children }) => (
            <th className="border px-2 py-1 text-left font-semibold">{children}</th>
          ),
          td: ({ children }) => <td className="border px-2 py-1 align-top">{children}</td>,
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

/**
 * Nhớ kết quả theo nội dung.
 *
 * Lúc đang streaming, mỗi mẩu chữ về là một lần vẽ lại; không chặn thì những
 * tin nhắn CŨ trong hội thoại cũng bị phân tích lại từ đầu theo.
 */
export const Markdown = memo(MarkdownGoc);
