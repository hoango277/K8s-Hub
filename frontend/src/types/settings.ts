/**
 * Cấu hình đổi được lúc chạy.
 *
 * Phải khớp với `backend/app/api/v1/settings.py`.
 */

export type FieldType =
  | "boolean"
  | "integer"
  | "number"
  | "string"
  | "enum"
  | "list"
  | "object"
  | "secret";

export interface SettingField {
  name: string;
  type: FieldType;
  /** Giá trị cho phép, chỉ có khi type === "enum" */
  options: string[] | null;
  minimum: number | null;
  maximum: number | null;
  exclusive_minimum: number | null;
  exclusive_maximum: number | null;
  secret: boolean;
  description: string;
  /** Giá trị hiện tại. Luôn null nếu là bí mật. */
  value: unknown;
  /** Bí mật đã được đặt chưa. Chỉ có ý nghĩa khi secret === true. */
  is_set: boolean | null;
  /** Giá trị gốc trong .env, dùng cho nút khôi phục. */
  env_value: unknown;
  /** Đang bị đổi so với .env hay không. */
  overridden: boolean;
}

export interface SettingsView {
  /** Tăng sau mỗi lần đổi. Dùng để phát hiện người khác vừa sửa. */
  version: number;
  fields: SettingField[];
  /** Phần đang ghi đè; giá trị bí mật đã được che thành "***". */
  overrides: Record<string, unknown>;
}

export interface SettingsPatch {
  /** Đặt null để bỏ ghi đè một trường, trả nó về giá trị trong .env. */
  values: Record<string, unknown>;
  replace?: boolean;
}

/** Nhóm hiển thị trên giao diện, suy ra từ tiền tố tên trường. */
export type SettingGroup = "LLM" | "Kubernetes" | "Quan sát" | "Chung";

export function groupOf(name: string): SettingGroup {
  if (name.startsWith("LLM_") || name.endsWith("_API_KEY")) return "LLM";
  if (name.startsWith("K8S_")) return "Kubernetes";
  if (name.startsWith("LANGFUSE_") || name.startsWith("PROMETHEUS_") || name.startsWith("LOKI_"))
    return "Quan sát";
  return "Chung";
}

export const GROUP_ORDER: SettingGroup[] = ["LLM", "Kubernetes", "Quan sát", "Chung"];

/** Những lựa chọn cần cảnh báo vì rủi ro cao. */
export const NGUY_HIEM: Record<string, string[]> = {
  K8S_EXECUTION_MODE: ["auto"],
};
