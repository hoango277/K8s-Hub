/**
 * Chuyển tiếp mọi lời gọi /api/backend/* sang backend FastAPI.
 *
 * VÌ SAO KHÔNG DÙNG `rewrites` TRONG next.config.ts:
 * rewrite gom toàn bộ phản hồi lại rồi mới trả về một lần. Với request thường
 * thì không sao, nhưng với luồng SSE thì hỏng hẳn: đo thực tế cho thấy 25 sự
 * kiện của một lượt trò chuyện về CÙNG MỘT LÚC ở giây thứ 12,7 thay vì rải ra
 * suốt 4 giây. Người dùng nhìn màn hình đứng im rồi câu trả lời hiện ra một
 * cục — mất đúng cái giá trị của streaming.
 *
 * Route handler thì trả thẳng `upstream.body` (một ReadableStream) nên dữ liệu
 * chảy tới đâu ra tới đó.
 *
 * Đi qua đây thay vì gọi thẳng backend từ trình duyệt để trình duyệt chỉ thấy
 * một nguồn duy nhất — không phải cấu hình CORS, và khoá API không bao giờ
 * phải lộ ra phía client.
 */

import type { NextRequest } from "next/server";

const BACKEND = process.env.BACKEND_URL ?? "http://localhost:8000";

// Luôn chạy động: có đệm ở tầng nào cũng làm hỏng streaming.
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

/** Header không được chuyển tiếp lên backend. */
const BO_QUA_GUI = new Set(["host", "connection", "content-length"]);

/**
 * Header không được sao chép về client.
 * Thân phản hồi đã được fetch giải nén rồi, giữ lại content-encoding hay
 * content-length cũ sẽ khiến trình duyệt đọc sai.
 */
const BO_QUA_NHAN = new Set([
  "content-encoding",
  "content-length",
  "transfer-encoding",
  "connection",
]);

async function chuyenTiep(
  req: NextRequest,
  ctx: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await ctx.params;
  const url = `${BACKEND}/api/v1/${path.join("/")}${req.nextUrl.search}`;

  const headers = new Headers();
  req.headers.forEach((v, k) => {
    if (!BO_QUA_GUI.has(k.toLowerCase())) headers.set(k, v);
  });

  const coThan = req.method !== "GET" && req.method !== "HEAD";

  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      // Đọc hết thân request trước khi gửi. Request của ta đều nhỏ, làm vậy
      // tránh phải bật chế độ truyền song công (duplex) của fetch.
      body: coThan ? await req.text() : undefined,
      cache: "no-store",
      // Người dùng đóng tab thì huỷ luôn lời gọi lên backend.
      signal: req.signal,
    });
  } catch {
    return Response.json(
      { detail: `Không kết nối được tới backend tại ${BACKEND}. Đã chạy chưa?` },
      { status: 502 },
    );
  }

  const resHeaders = new Headers();
  upstream.headers.forEach((v, k) => {
    if (!BO_QUA_NHAN.has(k.toLowerCase())) resHeaders.set(k, v);
  });

  if (resHeaders.get("content-type")?.includes("text/event-stream")) {
    resHeaders.set("Cache-Control", "no-cache, no-transform");
    // Báo cho nginx/ingress ở phía trước đừng gom dữ liệu lại.
    resHeaders.set("X-Accel-Buffering", "no");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: resHeaders,
  });
}

export const GET = chuyenTiep;
export const POST = chuyenTiep;
export const PATCH = chuyenTiep;
export const PUT = chuyenTiep;
export const DELETE = chuyenTiep;
