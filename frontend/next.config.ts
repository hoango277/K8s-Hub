import type { NextConfig } from "next";

// Không dùng `rewrites` để chuyển tiếp về backend nữa — nó gom cả phản hồi rồi
// mới trả về, làm hỏng luồng SSE của khung chat. Việc chuyển tiếp nay do
// src/app/api/backend/[...path]/route.ts đảm nhiệm.
const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
