/**
 * Khoá cache của TanStack Query, gom về một chỗ.
 *
 * Gõ tay chuỗi khoá ở mỗi nơi là cách nhanh nhất để có bug "sửa xong mà màn
 * hình không đổi": chỗ ghi dùng `["threads"]`, chỗ đọc dùng `["thread"]`, và
 * lệnh làm mới không khớp vào đâu cả.
 *
 * Khoá xếp theo thứ tự từ rộng đến hẹp, nên `invalidateQueries({queryKey:
 * qk.threads.all})` sẽ làm mới cả danh sách lẫn từng hội thoại con.
 */

export const qk = {
  threads: {
    all: ["threads"] as const,
    /** Mọi danh sách, bất kể có kèm hội thoại đã lưu trữ hay không. */
    lists: ["threads", "list"] as const,
    list: (includeArchived = false) => ["threads", "list", includeArchived] as const,
    detail: (id: string) => ["threads", "detail", id] as const,
  },
  chat: {
    tools: ["chat", "tools"] as const,
    providers: ["chat", "providers"] as const,
    models: (provider: string) => ["chat", "models", provider] as const,
  },
  settings: ["settings"] as const,
} as const;
