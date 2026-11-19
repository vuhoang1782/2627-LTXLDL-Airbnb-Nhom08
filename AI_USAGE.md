# AI_USAGE.md

> Bản nháp do một thành viên soạn. Mục có **[Nhóm điền]** cần cả nhóm bổ sung bằng thông tin thật. Khai báo đầy đủ không bị trừ điểm,
> giấu hoặc khai man là vi phạm chính sách AI.

## Công cụ đã dùng (vào việc gì)

- **Claude (Anthropic)**: viết và sửa mã nguồn quy trình (`src/`, `run_pipeline.py`), giải thích code, đề xuất cách trình bày mô tả KPI
  và QA, soạn README. Đầu ra do thành viên đọc, chạy thử và chỉnh lại.
- **Gemini API (gói miễn phí)**: phần phân tích review của quy trình (`src/llm.py`): cảm xúc, khía cạnh khen/chê, ngôn ngữ.
- **Không dùng AI** cho: gán 100 nhãn tay (làm bằng mắt, theo quy ước chung của nhóm). **[Nhóm điền]** các việc khác nhóm không dùng AI.

## Prompt then chốt (5-10): bước nào, vào tệp nào

1. Yêu cầu viết lại toàn bộ project theo `QA_SPEC_10_RULES.md`, `kpi.md` và đề bài, ưu tiên đơn giản, dễ học -> `src/qa.py`, `src/kpi.py`, `run_pipeline.py`.
2. Yêu cầu tích hợp `download.py` do bạn trong nhóm viết (tải + lọc theo tệp phân công) -> `src/download.py`.
3. Yêu cầu giải thích logic baseline không dùng LLM -> `src/baseline.py`.
4. Yêu cầu soạn mô tả 2 KPI theo 9 tiêu chí cho bên đặt hàng là công ty du lịch -> tài liệu KPI của nhóm.
5. Yêu cầu hướng dẫn gán nhãn tay (định nghĩa positive/mixed/negative, cách xử lý khía cạnh) -> quy ước gán nhãn.
6. **[Nhóm điền]** các prompt khác của từng thành viên.

## AI sai ở đâu (ví dụ thật)

1. AI từng nói dữ liệu mốc 3 và mốc 4 "mất 12 cột", nhưng số cột thực ra tăng; các cột đó vẫn có mặt nhưng gần như toàn ô rỗng. Phát hiện khi đối chiếu số cột 79, 85, 90, 90.
2. AI đề xuất nhãn tay `aspects_negative` (danh sách khía cạnh bị chê), không khớp quy ước của nhóm: mọi nhãn dùng thang positive / mixed / negative. Cường chỉ ra, nhóm đổi thành các nhãn cleanliness và host_friendliness.
3. Baseline bản đầu chỉ nhận dấu nháy thẳng nên câu "wasn’t clean" (nháy cong) bị chấm là positive. Phát hiện khi chạy thử và đã sửa bằng cách đổi nháy cong thành nháy thẳng trước khi tách từ.
4. Bản đầu của bước lọc coi ID trùng là lỗi và dừng cả quy trình, trong khi QA02 được thiết kế để xử lý ID trùng. Phát hiện khi chạy thử trên dữ liệu giả có cố ý chèn dòng trùng, đã đổi thành cảnh báo.
5. **[Nhóm điền]** các lỗi khác nhóm gặp.

## Nhóm kiểm chứng thế nào

- Chạy toàn bộ quy trình trên dữ liệu giả có chèn lỗi (giá thiếu/0/âm, amenities hỏng, dòng trùng hoàn toàn, khoá xung đột, ngày lịch thiếu, review rỗng, kết quả LLM sai định dạng) và kiểm tra `qa_report.csv`.
- Tính lại KPI 1, 2, 4, 5 và trạng thái T/F/U của KPI 3 bằng đoạn mã độc lập (duyệt từng listing, từng chuỗi 3 đêm) và so khớp với kết quả của `kpi.py`.
- Chạy trên pandas 2.3.3 và pandas 3, chạy từ thư mục khác, chạy khi không có tệp phân công.
- **[Nhóm điền]** việc nhóm tự kiểm chứng trên dữ liệu thật: đối chiếu số liệu `qa_report.csv`, xem tay mẫu review, độ chính xác LLM trên 100 nhãn tay, clone repo vào thư mục mới và chạy lại một lệnh.
