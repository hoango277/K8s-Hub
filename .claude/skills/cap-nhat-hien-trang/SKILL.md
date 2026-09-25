---
name: cap-nhat-hien-trang
description: Cập nhật docs/hien-trang-codebase.md của dự án K8s-Hub cho khớp với mã nguồn hiện tại. Dùng skill này bất cứ khi nào vừa làm xong một thay đổi đáng kể trong kho mã (viết module mới, vá lỗi, nối một tích hợp, thêm/bớt phụ thuộc, xoá file khung), hoặc khi người dùng hỏi về hiện trạng dự án, tiến độ, "còn thiếu gì", "đã làm được gì rồi", "báo cáo lại đi", hay yêu cầu cập nhật/viết lại báo cáo hiện trạng. Kể cả khi người dùng không nhắc tên file, nếu thay đổi vừa rồi làm báo cáo cũ sai thì hãy chủ động dùng skill này và nói cho họ biết.
---

# Cập nhật báo cáo hiện trạng codebase

`docs/hien-trang-codebase.md` là bản mô tả *những gì đang thực sự có* trong kho
mã K8s-Hub. Nó tồn tại vì dự án có rất nhiều file khung rỗng, và README thì mô
tả **kế hoạch** chứ không mô tả **thực tế**. Giá trị duy nhất của báo cáo này
nằm ở chỗ nó nói thật; một báo cáo lạc hậu còn tệ hơn không có báo cáo, vì
người đọc sẽ tin nó.

## Nguyên tắc số một: kiểm tận nguồn, đừng suy diễn

Mỗi khẳng định trong báo cáo phải được kiểm lại bằng cách **đọc mã hoặc chạy
thử**, không phải bằng cách đọc báo cáo cũ, đọc README, hay đọc docstring.

Đây không phải lời khuyên suông. Trong phiên viết ra báo cáo này đã xảy ra đúng
một lỗi kiểu đó: kết luận "hệ thống không đếm được token" chỉ vì API không trả
hai trường đó về. Thực tế cột `prompt_tokens` trong CSDL luôn có số liệu đúng —
lỗi nằm ở schema Pydantic thiếu khai trường, hoàn toàn không liên quan đến việc
đếm. Nếu lúc đó truy vấn thẳng bảng `messages` thì đã thấy ngay.

Rút ra: khi một tầng báo "không có gì", hãy đi xuống tầng dưới kiểm tiếp trước
khi kết luận. Dữ liệu vắng mặt ở API không có nghĩa là nó vắng mặt trong CSDL.

## Quy trình

### Bước 1 — Đọc báo cáo cũ như một danh sách giả thuyết

Đọc `docs/hien-trang-codebase.md`. Đừng coi nó là sự thật; coi mỗi khẳng định
là một điều **cần kiểm lại**. Chú ý mục 6 (rủi ro) và mục 7 (gợi ý bước tiếp) —
đó là hai chỗ lạc hậu nhanh nhất.

### Bước 2 — Quét lại thực tế

Chạy những lệnh này để có số liệu mới. Chúng đã được kiểm trong kho này.

```bash
# Đếm file Python mới chỉ là khung (docstring + TODO, không có mã).
# Bỏ __init__.py vì phần lớn chúng rỗng một cách hợp lệ — đếm vào sẽ thổi phồng
# con số lên khoảng 15 file và lệch với những lần báo cáo trước.
cd backend && for f in $(find app -name "*.py" -not -name "__init__.py" \
    -not -path "*__pycache__*"); do
  n=$(wc -l < "$f"); [ "$n" -le 3 ] && echo "$f"; done | wc -l

# Tổng số dòng Python và các file lớn nhất
find backend/app -name "*.py" -not -path "*__pycache__*" -exec wc -l {} + | sort -rn | head -20

# File khung phía frontend (component trả về null, hook chỉ có comment)
cd frontend && for f in $(find src -name "*.ts*"); do
  n=$(wc -l < "$f"); [ "$n" -le 16 ] && echo "$n $f"; done | sort -n

# Bộ test còn xanh không
cd backend && PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest -q 2>&1 | tail -3

# Lint
cd backend && .venv/Scripts/python.exe -m ruff check app/ 2>&1 | tail -3
cd frontend && npm run typecheck
```

Sau đó đọc kỹ những file đã đổi kể từ lần cập nhật trước. Nếu không biết đã đổi
gì, so mốc thời gian sửa file với ngày ghi ở đầu báo cáo:

```bash
find backend/app frontend/src -type f \( -name "*.py" -o -name "*.ts*" \) \
  -not -path "*__pycache__*" -newermt "<ngày ghi ở đầu báo cáo>" | head -40
```

### Bước 3 — Đối chiếu từng khẳng định

Với mỗi mục trong báo cáo cũ, xác định: **vẫn đúng / đã sai / đã mất ý nghĩa**.
Đặc biệt kiểm ba loại sau, vì chúng là chỗ báo cáo hay nói dối nhất:

- **File từng là khung nay đã có mã** — phải chuyển từ mục 4 sang mục 3.
- **Rủi ro đã được vá** — phải ghi rõ là đã vá, đừng xoá lặng lẽ (xem bên dưới).
- **Phụ thuộc mới** — so `backend/requirements.txt` và `pyproject.toml` với
  những gì thực sự được import trong `app/`.

### Bước 4 — Viết lại

Sửa tại chỗ, giữ nguyên bố cục. Cập nhật dòng ngày ở đầu file và dòng ghi chú ở
cuối file. Nếu số liệu tổng quan (số dòng, số file khung) đổi thì sửa cả bảng
tóm tắt ở mục 1 — bảng đó là thứ người ta đọc đầu tiên.

## Bố cục phải giữ nguyên

Báo cáo có bảy mục, đừng đổi thứ tự hay đánh số lại:

```
# Hiện trạng codebase K8s Hub
*Báo cáo đọc mã, cập nhật ngày <dd/mm/yyyy>. ...*
## 1. Tóm tắt trong một trang        (bảng trạng thái từng mảng + nhận định chung)
## 2. Bản đồ kho mã                  (cây thư mục kèm chú thích)
## 3. Những gì đã chạy được          (chia 3.1, 3.2, ... theo mảng)
## 4. Những gì mới là khung
## 5. Vận hành và triển khai
## 6. Khoảng trống và rủi ro cần biết (sắp theo mức độ nên xử lý sớm)
## 7. Gợi ý thứ tự làm tiếp
```

## Ranh giới giữa "đã chạy được" và "khung"

Một phần chỉ được xếp vào mục 3 khi **có mã thật chạy được đầu-cuối**. Dấu hiệu
một file mới chỉ là khung: Python có 1 dòng docstring kết thúc bằng `TODO`;
TypeScript là component `return null` hoặc file chỉ có comment.

Trường hợp lỡ cỡ — có mã nhưng chưa ai gọi tới — thì xếp vào mục 3 kèm câu nói
rõ là chưa được nối vào luồng nào. Đừng để người đọc tưởng nó đang hoạt động.

## Mục 6 xử lý thế nào

Rủi ro đã được vá thì **đừng xoá đi im lặng**. Chuyển nó thành một dòng ngắn ghi
đã vá và vá bằng cách nào, hoặc gom vào một tiểu mục "đã xử lý". Người đọc quay
lại sau vài tuần cần thấy được vấn đề đó từng tồn tại và đã được giải quyết —
xoá sạch thì lần sau có ai gặp lại sẽ tưởng là chuyện mới.

Rủi ro mới phát hiện thì thêm vào, và sắp lại cả danh sách theo mức độ nên xử lý
sớm chứ không phải theo thứ tự tìm ra.

## Những cái bẫy của kho mã này

- **`git` không chạy được** ở thư mục này: Windows báo "dubious ownership" vì kho
  được tạo từ một tài khoản khác. Nên dùng `find` thay cho `git ls-files`. Nếu
  thật sự cần git: `git -c safe.directory=D:/SCHOOL/K8s-Hub <lệnh>`.
- **Console Windows là cp1252**, in tiếng Việt sẽ ném `UnicodeEncodeError`. Đặt
  `PYTHONUTF8=1` trước mọi lệnh Python.
- **Python của backend nằm ở `backend/.venv/Scripts/python.exe`**, không phải
  `python` trên PATH.
- **README mô tả kế hoạch, không mô tả thực tế.** Đừng lấy nó làm nguồn.
  Riêng `app/core/telemetry.py` và mục "lớp C" trong hai file README hiện đang
  mô tả thứ chưa được viết — nếu chép lại là báo cáo sai ngay.
- **Đây là việc chỉ đọc.** Không khởi động server, không chạy migration, không
  sửa mã nguồn. Kết quả duy nhất được phép ghi ra là `docs/hien-trang-codebase.md`.

## Viết bằng tiếng Việt

Cả kho mã và báo cáo đều dùng tiếng Việt. Thuật ngữ Kubernetes và tên thư viện
giữ nguyên tiếng Anh. Giọng văn: nói thẳng, có số liệu, nêu lý do — không tô hồng
tiến độ, vì mục đích của tài liệu này là để người đọc biết mình đang đứng ở đâu.
