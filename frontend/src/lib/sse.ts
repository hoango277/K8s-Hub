/**
 * Đọc luồng SSE bằng `fetch`.
 *
 * Vì sao không dùng `EventSource` có sẵn của trình duyệt: `EventSource` chỉ
 * gửi được GET, mà câu hỏi của người dùng phải nằm trong thân request (POST).
 * Nó cũng không gắn được header. Đổi lại, phải tự tách khung SSE — phần đó
 * nằm gọn trong file này.
 *
 * Định dạng SSE: mỗi khung là các dòng `field: value`, kết thúc bằng một dòng
 * trống. Dòng bắt đầu bằng ':' là chú thích — nhịp giữ kết nối của máy chủ đi
 * bằng đường này, và phải bỏ qua.
 */

import { parseAgentEvent, type AgentEvent } from "@/types/events";

export interface SseOptions {
  signal?: AbortSignal;
  /** Gọi khi máy chủ trả lỗi HTTP trước khi luồng kịp mở. */
  onHttpError?: (status: number, body: string) => void;
}

/** Một khung SSE đã tách xong. */
interface Frame {
  event: string;
  data: string;
  id: string;
}

function parseFrame(khoi: string): Frame | null {
  const frame: Frame = { event: "message", data: "", id: "" };
  const data: string[] = [];

  for (const line of khoi.split("\n")) {
    if (!line || line.startsWith(":")) continue; // dòng trống hoặc chú thích

    const viTri = line.indexOf(":");
    const field = viTri === -1 ? line : line.slice(0, viTri);
    // Bỏ đúng MỘT dấu cách sau dấu hai chấm, theo đúng đặc tả.
    let value = viTri === -1 ? "" : line.slice(viTri + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    if (field === "event") frame.event = value;
    else if (field === "data") data.push(value);
    else if (field === "id") frame.id = value;
  }

  if (data.length === 0) return null;
  frame.data = data.join("\n");
  return frame;
}

/**
 * Gửi POST và sinh ra từng sự kiện của trợ lý theo thời gian thực.
 *
 * Sự kiện không đúng định dạng bị bỏ qua thay vì làm hỏng cả luồng — một
 * khung lỗi không đáng để mất phần còn lại của câu trả lời.
 */
export async function* streamAgentEvents(
  url: string,
  body: unknown,
  options: SseOptions = {},
): AsyncGenerator<AgentEvent> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    options.onHttpError?.(res.status, text);
    throw new Error(text || `Lỗi ${res.status}`);
  }
  if (!res.body) throw new Error("Máy chủ không trả về luồng dữ liệu");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let dem = "";

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;

      // stream: true để ký tự nhiều byte bị cắt giữa hai gói vẫn ghép lại đúng.
      dem += decoder.decode(value, { stream: true });

      // Khung kết thúc bằng dòng trống. Chấp nhận cả \n\n lẫn \r\n\r\n.
      let ranh: number;
      while ((ranh = timRanhKhung(dem)) !== -1) {
        const khoi = dem.slice(0, ranh);
        dem = dem.slice(ranh).replace(/^(\r?\n){2}/, "");

        const frame = parseFrame(khoi);
        if (!frame) continue;

        const event = parseAgentEvent(frame.data);
        if (event) yield event;
      }
    }
  } finally {
    // Dừng giữa chừng thì phải đóng, không thì kết nối treo lại.
    reader.cancel().catch(() => undefined);
  }
}

function timRanhKhung(text: string): number {
  const a = text.indexOf("\n\n");
  const b = text.indexOf("\r\n\r\n");
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}
