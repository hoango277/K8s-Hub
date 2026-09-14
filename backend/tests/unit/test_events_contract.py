"""Kiểm tra hợp đồng sự kiện: backend và frontend phải khớp nhau.

Bài test này bắt lỗi khi ai đó sửa `app/schemas/events.py` mà quên sửa
`frontend/src/types/events.ts` (hoặc ngược lại).

Chạy: pytest tests/unit/test_events_contract.py -v
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.schemas import events as ev

TS_FILE = Path(__file__).resolve().parents[3] / "frontend" / "src" / "types" / "events.ts"

# Trường chỉ có ở backend, không cần xuất hiện ở frontend.
BACKEND_ONLY_FIELDS: dict[str, set[str]] = {}


def _strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _parse_ts_interfaces(src: str) -> dict[str, set[str]]:
    """Trả về {tên interface: {tên trường}} từ file .ts."""
    src = _strip_comments(src)
    out: dict[str, set[str]] = {}
    for m in re.finditer(
        r"export\s+interface\s+(\w+)(?:\s+extends\s+[\w,\s]+)?\s*\{(.*?)\n\}",
        src,
        flags=re.S,
    ):
        name, body = m.group(1), m.group(2)
        out[name] = set(re.findall(r"^\s*(\w+)\??\s*:", body, flags=re.M))
    return out


def _parse_ts_union(src: str) -> set[str]:
    """Trả về tập giá trị trong mảng AGENT_EVENT_TYPES."""
    src = _strip_comments(src)
    m = re.search(r"AGENT_EVENT_TYPES\s*=\s*\[(.*?)\]", src, flags=re.S)
    assert m, "Không tìm thấy AGENT_EVENT_TYPES trong events.ts"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _event_models() -> dict[str, type[BaseModel]]:
    """Mọi model sự kiện ở backend, khoá theo giá trị `type`."""
    out: dict[str, type[BaseModel]] = {}
    for name in ev.__all__:
        obj = getattr(ev, name)
        if (
            isinstance(obj, type)
            and issubclass(obj, ev.BaseEvent)
            and obj is not ev.BaseEvent
        ):
            out[obj.model_fields["type"].default] = obj
    return out


@pytest.fixture(scope="module")
def ts_src() -> str:
    assert TS_FILE.exists(), f"Không thấy {TS_FILE}"
    return TS_FILE.read_text(encoding="utf-8")


def test_file_frontend_ton_tai(ts_src: str) -> None:
    assert "AgentEvent" in ts_src


def test_cung_tap_loai_su_kien(ts_src: str) -> None:
    """Backend và frontend phải khai báo đúng cùng một tập `type`."""
    backend_types = set(_event_models())
    ts_types = _parse_ts_union(ts_src)

    assert backend_types == ts_types, (
        f"Lệch tập loại sự kiện.\n"
        f"  Chỉ có ở backend : {sorted(backend_types - ts_types)}\n"
        f"  Chỉ có ở frontend: {sorted(ts_types - backend_types)}"
    )


def test_cung_ten_truong(ts_src: str) -> None:
    """Mỗi loại sự kiện phải có cùng danh sách trường ở hai bên."""
    ts_ifaces = _parse_ts_interfaces(ts_src)
    base_fields = ts_ifaces.get("BaseEvent", set())

    loi: list[str] = []
    for type_value, model in sorted(_event_models().items()):
        iface = model.__name__
        if iface not in ts_ifaces:
            loi.append(f"  {type_value}: frontend thiếu interface {iface}")
            continue

        py_fields = set(model.model_fields) - BACKEND_ONLY_FIELDS.get(type_value, set())
        ts_fields = ts_ifaces[iface] | base_fields

        if py_fields != ts_fields:
            loi.append(
                f"  {type_value} ({iface}):\n"
                f"      chỉ có ở backend : {sorted(py_fields - ts_fields)}\n"
                f"      chỉ có ở frontend: {sorted(ts_fields - py_fields)}"
            )

    assert not loi, "Lệch tên trường giữa hai file:\n" + "\n".join(loi)


def test_model_phu_khop(ts_src: str) -> None:
    """Các model không phải sự kiện (PlanStep) cũng phải khớp."""
    ts_ifaces = _parse_ts_interfaces(ts_src)
    assert set(ev.PlanStep.model_fields) == ts_ifaces.get("PlanStep", set())


def test_seq_duoc_danh_so_tu_1() -> None:
    stream = ev.EventStream()
    frames = [stream.emit(ev.TokenEvent(content=str(i))) for i in range(3)]
    assert [f["id"] for f in frames] == ["1", "2", "3"]


def test_ten_event_sse_trung_voi_type() -> None:
    frame = ev.to_sse(ev.DoneEvent(trace_id="x"))
    assert frame["event"] == "done"


def test_truong_none_khong_len_duong_truyen() -> None:
    """exclude_none để frontend nhận đúng optional field."""
    frame = ev.to_sse(ev.DoneEvent())
    assert "trace_id" not in frame["data"]


def test_chan_type_la() -> None:
    with pytest.raises(Exception):
        ev.AgentEventAdapter.validate_python({"type": "khong_co_that", "seq": 1})


def test_chan_truong_thua() -> None:
    with pytest.raises(Exception):
        ev.TokenEvent(content="x", truong_la=1)
