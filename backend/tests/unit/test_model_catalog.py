"""Kiểm tra việc đọc danh sách model từ nhà cung cấp.

Dữ liệu mẫu bên dưới lấy từ phản hồi THẬT của API (Groq đã gọi trực tiếp;
Google và Anthropic theo tài liệu của họ). Giữ nguyên hình dạng đó là có chủ ý:
nhà cung cấp đổi cấu trúc trả về thì test này phải đỏ, chứ không phải để giao
diện lặng lẽ hiện ô chọn trống.
"""

from __future__ import annotations

from app.integrations.llm.catalog import (
    GOOGLE_KHONG_PHAI_CHAT,
    MIN_CONTEXT_WINDOW,
    _doc_anthropic,
    _doc_google,
    _doc_openai,
)

# Rút gọn từ phản hồi thật của https://api.groq.com/openai/v1/models
GROQ_THAT = {
    "object": "list",
    "data": [
        {
            "id": "openai/gpt-oss-120b",
            "name": "GPT OSS 120B",
            "owned_by": "OpenAI",
            "active": True,
            "context_window": 131072,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            # Nhận dạng giọng nói — không trò chuyện được.
            "id": "whisper-large-v3",
            "name": "Whisper Large v3",
            "owned_by": "OpenAI",
            "active": True,
            "context_window": 448,
            "input_modalities": ["audio"],
            "output_modalities": ["transcription"],
        },
        {
            # Đọc thành tiếng — nhận chữ nhưng nhả âm thanh.
            "id": "canopylabs/orpheus-v1-english",
            "name": "Orpheus",
            "owned_by": "Canopy Labs",
            "active": True,
            "context_window": 4000,
            "input_modalities": ["text"],
            "output_modalities": ["speech"],
        },
        {
            # Bộ phân loại nội dung: chữ vào, chữ ra, nhưng cửa sổ chỉ 512.
            "id": "meta-llama/llama-prompt-guard-2-86m",
            "name": "Llama Prompt Guard 2 86M",
            "owned_by": "Meta",
            "active": True,
            "context_window": 512,
            "input_modalities": ["text"],
            "output_modalities": ["text"],
        },
        {
            "id": "qwen/qwen3.6-27b",
            "name": "Qwen3.6 27B",
            "owned_by": "Alibaba Cloud",
            "active": True,
            "context_window": 131072,
            "input_modalities": ["text", "image"],
            "output_modalities": ["text"],
        },
    ],
}


def ma_list(models) -> list[str]:
    return [m.id for m in models]


# --------------------------------------------------------------------------
# Groq / API tương thích OpenAI
# --------------------------------------------------------------------------


def test_bo_model_nhan_am_thanh():
    """Whisper nhận âm thanh, đưa vào ô chọn là người dùng chọn nhầm."""
    assert "whisper-large-v3" not in ma_list(_doc_openai(GROQ_THAT))


def test_bo_model_nha_am_thanh():
    """Orpheus nhận chữ nhưng nhả tiếng — lọc bằng output_modalities."""
    assert "canopylabs/orpheus-v1-english" not in ma_list(_doc_openai(GROQ_THAT))


def test_bo_bo_phan_loai_cua_so_qua_nho():
    """prompt-guard là chữ vào - chữ ra nên modality không lọc được.

    Nó bị loại vì cửa sổ 512 token, không đủ chứa nổi lời nhắc hệ thống.
    """
    assert "meta-llama/llama-prompt-guard-2-86m" not in ma_list(_doc_openai(GROQ_THAT))


def test_giu_model_tro_chuyen():
    ket_qua = ma_list(_doc_openai(GROQ_THAT))
    assert "openai/gpt-oss-120b" in ket_qua
    # Model nhận thêm ảnh vẫn là model trò chuyện, không được loại.
    assert "qwen/qwen3.6-27b" in ket_qua


def test_lay_dung_ten_hien_thi_va_cua_so():
    m = next(m for m in _doc_openai(GROQ_THAT) if m.id == "openai/gpt-oss-120b")
    assert m.label == "GPT OSS 120B"
    assert m.context_window == 131072
    assert m.owned_by == "OpenAI"


def test_bo_model_da_tat():
    data = {"data": [{**GROQ_THAT["data"][0], "active": False}]}
    assert _doc_openai(data) == []


def test_thieu_truong_modality_thi_van_giu():
    """API tương thích OpenAI khác có thể không khai modality.

    Thiếu thông tin thì cho qua, đừng lọc sạch danh sách của người ta.
    """
    data = {"data": [{"id": "mot-model-nao-do", "context_window": 8192}]}
    assert ma_list(_doc_openai(data)) == ["mot-model-nao-do"]


def test_nguong_cua_so_dung_hang_so_chung():
    """Chặn kiểu 'sửa hằng số mà quên sửa chỗ lọc'."""
    data = {
        "data": [
            {"id": "vua-du", "context_window": MIN_CONTEXT_WINDOW},
            {"id": "thieu-mot-chut", "context_window": MIN_CONTEXT_WINDOW - 1},
        ]
    }
    assert ma_list(_doc_openai(data)) == ["vua-du"]


def test_du_lieu_la_khong_lam_vo():
    assert _doc_openai({}) == []
    assert _doc_openai({"data": [None, "chuoi", 123]}) == []
    assert _doc_openai({"data": [{"khong_co_id": 1}]}) == []


# --------------------------------------------------------------------------
# Google Gemini
# --------------------------------------------------------------------------

GOOGLE_MAU = {
    "models": [
        {
            "name": "models/gemini-2.5-flash",
            "displayName": "Gemini 2.5 Flash",
            "inputTokenLimit": 1048576,
            "supportedGenerationMethods": ["generateContent", "countTokens"],
        },
        {
            # Model nhúng — không trò chuyện được.
            "name": "models/text-embedding-004",
            "displayName": "Text Embedding 004",
            "inputTokenLimit": 2048,
            "supportedGenerationMethods": ["embedContent"],
        },
    ]
}


def test_google_bo_tien_to_models():
    """Tên về là 'models/gemini-...' nhưng lúc gọi phải bỏ tiền tố đó.

    Không bỏ thì mọi lời gọi đều lỗi 404 ở phía nhà cung cấp.
    """
    assert ma_list(_doc_google(GOOGLE_MAU)) == ["gemini-2.5-flash"]


def test_google_bo_model_khong_sinh_noi_dung():
    assert "text-embedding-004" not in ma_list(_doc_google(GOOGLE_MAU))


def test_google_lay_gioi_han_token_lam_cua_so():
    m = _doc_google(GOOGLE_MAU)[0]
    assert m.label == "Gemini 2.5 Flash"
    assert m.context_window == 1048576


def test_google_du_lieu_la():
    assert _doc_google({}) == []
    assert _doc_google({"models": [{"name": "models/"}]}) == []


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------


def test_anthropic_giu_nguyen_tat_ca():
    data = {
        "data": [
            {"type": "model", "id": "claude-sonnet-5", "display_name": "Claude Sonnet 5"}
        ]
    }
    m = _doc_anthropic(data)[0]
    assert m.id == "claude-sonnet-5"
    assert m.label == "Claude Sonnet 5"


def test_anthropic_thieu_ten_hien_thi_thi_dung_id():
    data = {"data": [{"id": "claude-x"}]}
    assert _doc_anthropic(data)[0].label == "claude-x"


def test_anthropic_du_lieu_la():
    assert _doc_anthropic({}) == []


def test_google_bo_model_khong_sinh_ra_chu():
    """Google khai TẤT CẢ là 'generateContent', kể cả model sinh ảnh và đọc
    thành tiếng. Danh sách dưới đây là id THẬT lấy từ API."""
    data = {
        "models": [
            {"name": f"models/{ma}", "supportedGenerationMethods": ["generateContent"]}
            for ma in (
                "gemini-2.5-flash",
                "gemini-2.5-flash-image",        # Nano Banana, sinh ảnh
                "nano-banana-pro-preview",       # sinh ảnh
                "gemini-2.5-flash-preview-tts",  # đọc thành tiếng
                "gemini-3.1-flash-tts-preview",
                "lyria-3.5",                     # sinh nhạc
                "gemini-3.5-transcribe",         # nhận giọng nói
                "gemini-3.5-flash",
            )
        ]
    }
    assert ma_list(_doc_google(data)) == ["gemini-2.5-flash", "gemini-3.5-flash"]


def test_google_khong_loc_qua_tay():
    """Model trò chuyện có tên lạ vẫn phải được giữ.

    Giấu mất một model dùng được thì người dùng không có đường nào chọn nó.
    """
    data = {
        "models": [
            {"name": f"models/{ma}", "supportedGenerationMethods": ["generateContent"]}
            for ma in (
                "gemma-4-31b-it",
                "deep-research-pro-preview-12-2025",
                "gemini-2.5-computer-use-preview-10-2025",
            )
        ]
    }
    assert len(_doc_google(data)) == 3


def test_danh_sach_loai_tru_khong_rong():
    """Chặn kiểu vô tình xoá sạch danh sách loại trừ."""
    assert len(GOOGLE_KHONG_PHAI_CHAT) >= 5
