"""Lấy danh sách model trực tiếp từ nhà cung cấp.

Vì sao không viết sẵn danh sách trong code: các nhà cung cấp cho model nghỉ
hưu và ra model mới liên tục. Một danh sách viết cứng sẽ sai trong vòng vài
tháng, và cái sai đó chỉ lộ ra khi người dùng chọn phải một model đã bị gỡ.

Ba nhà cung cấp trả về ba dạng khác nhau, và xác thực cũng khác nhau. Khác
biệt đó nằm gọn trong `_DOC` ở dưới; thêm nhà cung cấp mới chỉ cần khai
`models_url` và `models_style` trong cấu hình.

LỌC MODEL — đọc kỹ phần này:

Danh sách thô chứa cả những model không dùng để trò chuyện được. Groq trả về
cả `whisper-large-v3` (nhận dạng giọng nói) lẫn `orpheus-*` (đọc thành tiếng)
và `llama-prompt-guard-*` (bộ phân loại nội dung). Đưa hết lên giao diện thì
người dùng sẽ chọn nhầm, và lỗi chỉ hiện ra sau khi đã gửi câu hỏi.

Việc lọc dựa trên trường DỮ LIỆU nhà cung cấp trả về, không dựa vào tên model:
lọc theo tên là kiểu vá tạm, model mới ra là hỏng lại.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from app.core.config import ProviderConfig, get_settings, on_reload

logger = logging.getLogger(__name__)

# Danh sách model hiếm khi đổi trong một phiên làm việc. Hỏi lại nhà cung cấp
# ở mỗi lần mở trang là chậm và tốn hạn mức vô ích.
CACHE_TTL_SECONDS = 600

REQUEST_TIMEOUT = 15.0

# Ngưỡng cửa sổ ngữ cảnh tối thiểu để coi là model trò chuyện được.
#
# Đây là một PHỎNG ĐOÁN, và nó tồn tại vì một lý do cụ thể: các bộ phân loại
# như llama-prompt-guard có cửa sổ 512 token, trong khi riêng lời nhắc hệ thống
# kèm mô tả công cụ của ta đã ngót 700 token. Chúng không thể dùng để chat, dù
# vẫn là text vào - text ra nên không lọc được bằng modality.
MIN_CONTEXT_WINDOW = 2048


class ModelInfo(BaseModel):
    """Một model dùng được cho khung chat."""

    id: str = Field(description="Tên truyền cho API, ví dụ 'openai/gpt-oss-120b'")
    label: str = Field(description="Tên hiển thị cho người dùng")
    context_window: int | None = None
    owned_by: str | None = None


class ModelCatalog(BaseModel):
    """Kết quả tra danh sách model của một nhà cung cấp."""

    provider: str
    models: list[ModelInfo]
    source: str = Field(description="'api' = lấy từ nhà cung cấp, 'config' = từ cấu hình")
    error: str | None = Field(
        default=None,
        description="Lý do không lấy được từ API. Có giá trị này thì source='config'.",
    )


# --------------------------------------------------------------------------
# Đọc từng dạng trả về
# --------------------------------------------------------------------------


def _doc_openai(data: dict[str, Any]) -> list[ModelInfo]:
    """Groq và mọi API tương thích OpenAI.

    Lọc theo modality: bỏ model nhận âm thanh (whisper) và model nhả âm thanh
    (orpheus). Còn lại lọc theo cửa sổ ngữ cảnh để bỏ bộ phân loại.
    """
    ra: list[ModelInfo] = []
    for m in data.get("data") or []:
        if not isinstance(m, dict) or m.get("active") is False:
            continue

        vao = m.get("input_modalities")
        khoi = m.get("output_modalities")
        # Không khai báo modality thì cho qua — coi như model chữ bình thường.
        if isinstance(vao, list) and "text" not in vao:
            continue
        if isinstance(khoi, list) and "text" not in khoi:
            continue

        ctx = m.get("context_window") or m.get("context_length")
        if isinstance(ctx, int) and ctx < MIN_CONTEXT_WINDOW:
            continue

        ma = m.get("id")
        if not ma:
            continue
        ra.append(
            ModelInfo(
                id=str(ma),
                label=str(m.get("name") or ma),
                context_window=ctx if isinstance(ctx, int) else None,
                owned_by=m.get("owned_by"),
            )
        )
    return ra


# Google KHÔNG có trường nào cho biết model sinh ra thứ gì.
#
# Groq khai `output_modalities` nên lọc được đàng hoàng. Google thì model sinh
# ảnh (Nano Banana), đọc thành tiếng (TTS), sinh nhạc (Lyria) và model trò
# chuyện đều khai y hệt nhau: `generateContent`. Đã kiểm tra trực tiếp trên API
# — không có `outputModalities`, không có `supportedActions`, không có gì khác.
#
# Nên chỗ này buộc phải lọc theo TÊN. Đây là cách vá tạm và nó có hạn: Google
# ra một dòng model kiểu mới với tên lạ thì model đó sẽ lọt vào danh sách. Chọn
# cách để lọt còn hơn để thiếu — người dùng thấy một mục lạ thì bỏ qua, chứ
# model dùng được mà bị giấu thì không có đường nào chọn.
GOOGLE_KHONG_PHAI_CHAT = (
    "-image",        # sinh ảnh
    "nano-banana",   # sinh ảnh (tên thương mại)
    "tts",           # đọc thành tiếng
    "lyria",         # sinh nhạc
    "transcribe",    # chuyển giọng nói thành chữ
    "embedding",     # vector nhúng
    "imagen",
    "veo",           # sinh video
)


def _doc_google(data: dict[str, Any]) -> list[ModelInfo]:
    """Google Gemini.

    Tên model về dưới dạng 'models/gemini-2.5-flash' nhưng lúc gọi thì phải bỏ
    tiền tố 'models/'. Chỉ lấy model có 'generateContent', rồi loại tiếp những
    model không sinh ra chữ (xem GOOGLE_KHONG_PHAI_CHAT ở trên).
    """
    ra: list[ModelInfo] = []
    for m in data.get("models") or []:
        if not isinstance(m, dict):
            continue
        if "generateContent" not in (m.get("supportedGenerationMethods") or []):
            continue

        ten = str(m.get("name") or "")
        ma = ten.removeprefix("models/")
        if not ma:
            continue
        if any(tu in ma.lower() for tu in GOOGLE_KHONG_PHAI_CHAT):
            continue
        ra.append(
            ModelInfo(
                id=ma,
                label=str(m.get("displayName") or ma),
                context_window=m.get("inputTokenLimit"),
                owned_by="Google",
            )
        )
    return ra


def _doc_anthropic(data: dict[str, Any]) -> list[ModelInfo]:
    """Anthropic. Mọi model trả về đều là model trò chuyện, không cần lọc."""
    ra: list[ModelInfo] = []
    for m in data.get("data") or []:
        if not isinstance(m, dict):
            continue
        ma = m.get("id")
        if not ma:
            continue
        ra.append(
            ModelInfo(
                id=str(ma),
                label=str(m.get("display_name") or ma),
                owned_by="Anthropic",
            )
        )
    return ra


_DOC = {
    "openai": _doc_openai,
    "google": _doc_google,
    "anthropic": _doc_anthropic,
}


def _chuan_bi_request(spec: ProviderConfig, api_key: str) -> tuple[dict, dict]:
    """Trả về (headers, params) đúng kiểu xác thực của nhà cung cấp."""
    if spec.models_style == "google":
        # Google nhận khoá qua query param chứ không qua header.
        return {}, {"key": api_key, "pageSize": 200}

    if spec.models_style == "anthropic":
        return (
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            {"limit": 100},
        )

    return {"Authorization": f"Bearer {api_key}"}, {}


# --------------------------------------------------------------------------
# Bộ nhớ đệm
# --------------------------------------------------------------------------

_cache: dict[str, tuple[float, ModelCatalog]] = {}


@on_reload
def clear_cache() -> None:
    """Cấu hình đổi (thường là đổi khoá API) thì danh sách cũ không còn đúng."""
    _cache.clear()


def _tu_cau_hinh(provider: str, spec: ProviderConfig, ly_do: str | None) -> ModelCatalog:
    """Phương án dự phòng: dùng model đã khai trong cấu hình.

    Luôn có cái gì đó để chọn, kể cả khi mạng hỏng hoặc chưa điền khoá API.
    """
    thay: list[ModelInfo] = []
    for ma in (spec.model, spec.fast_model):
        if ma and all(m.id != ma for m in thay):
            thay.append(ModelInfo(id=ma, label=ma))
    return ModelCatalog(
        provider=provider, models=thay, source="config", error=ly_do
    )


async def list_models(provider: str | None = None, *, refresh: bool = False) -> ModelCatalog:
    """Danh sách model dùng được của một nhà cung cấp.

    KHÔNG ném ngoại lệ khi nhà cung cấp lỗi. Giao diện chọn model không đáng để
    làm hỏng cả trang: trả về model trong cấu hình kèm lý do, người dùng vẫn
    chat được.
    """
    config = get_settings()
    ten = provider or config.LLM_PROVIDER
    spec = config.llm_provider(ten)

    if not refresh:
        dem = _cache.get(ten)
        if dem and (time.monotonic() - dem[0]) < CACHE_TTL_SECONDS:
            return dem[1]

    if not spec.models_url:
        return _tu_cau_hinh(ten, spec, "Nhà cung cấp này chưa khai địa chỉ API liệt kê model")

    api_key = str(getattr(config, spec.api_key_field, "") or "").strip()
    if not api_key:
        return _tu_cau_hinh(ten, spec, f"Chưa điền {spec.api_key_field}")

    headers, params = _chuan_bi_request(spec, api_key)

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(spec.models_url, headers=headers, params=params)

        if resp.status_code != 200:
            # Không đưa nội dung lỗi thô ra ngoài: một số nhà cung cấp vọng lại
            # cả khoá API trong thông báo lỗi.
            return _tu_cau_hinh(
                ten, spec, f"Nhà cung cấp trả về lỗi {resp.status_code}"
            )

        doc = _DOC.get(spec.models_style, _doc_openai)
        models = doc(resp.json())

    except Exception as exc:
        logger.warning("Không lấy được danh sách model của %s: %s", ten, exc)
        return _tu_cau_hinh(ten, spec, f"Không gọi được API: {type(exc).__name__}")

    if not models:
        return _tu_cau_hinh(ten, spec, "Nhà cung cấp không trả về model nào dùng được")

    # Model đang đặt trong cấu hình phải luôn có trong danh sách, kể cả khi nhà
    # cung cấp không còn liệt kê nó — nếu không, giao diện sẽ hiện ô chọn trống
    # trong khi hệ thống vẫn đang chạy bằng chính model đó.
    #
    # Chỉ làm vậy cho nhà cung cấp ĐANG DÙNG: `LLM_MODEL` trong .env là một tên
    # duy nhất, gắn với nhà cung cấp đang đặt. Nhét nó vào danh sách của nhà
    # cung cấp khác là chèn một model không tồn tại ở đó.
    if ten == config.LLM_PROVIDER:
        dang_dung = config.llm_model_name(provider=ten)
        if dang_dung and all(m.id != dang_dung for m in models):
            models.insert(0, ModelInfo(id=dang_dung, label=f"{dang_dung} (đang dùng)"))

    models.sort(key=lambda m: m.label.lower())
    ket_qua = ModelCatalog(provider=ten, models=models, source="api")
    _cache[ten] = (time.monotonic(), ket_qua)
    return ket_qua


__all__ = [
    "CACHE_TTL_SECONDS",
    "MIN_CONTEXT_WINDOW",
    "ModelCatalog",
    "ModelInfo",
    "clear_cache",
    "list_models",
]
