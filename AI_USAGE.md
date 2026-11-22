# AI_USAGE.md

## Công cụ đã dùng

- **ChatGPT:** hỗ trợ lên ý tưởng, lập kế hoạch KPI/QA, soạn prompt, giải thích code và số liệu báo cáo, gợi ý lệnh commit, kiểm tra nhãn tay sau khi gán.
- **Claude:** xây dựng khung và mã nguồn chính ban đầu (`src/`, `run_pipeline.py`, cấu hình), tạo các bước xuất `reports/`, `figures/`; hỗ trợ soạn `README.md`, `AI_USAGE.md`, `requirements.txt` và các tệp thiết lập dự án.
- **Codex:** chỉnh KPI 2 theo mục đích mới và cập nhật QA liên quan; sửa `src/viz.py` để biểu đồ dễ đọc; chỉnh cấu hình, README, thư viện và tối ưu code. Hỗ trợ sửa phần đánh giá, chạy thử pipeline, phát hiện lỗi và viết báo cáo.
- **Gemini API (gói miễn phí):**  gọi trong `src/llm.py` để phân tích cảm xúc, khía cạnh khen/chê và ngôn ngữ của review

## Prompt then chốt (5–10):


| Bước / công cụ | Nội dung yêu cầu chính | Tệp áp dụng hoặc đầu ra |
|---|---|---|
| 1. Khởi tạo — Claude | Xây dựng project theo đề bài, bộ 10 quy tắc QA và các KPI; ưu tiên code đơn giản, dễ giải thích. | `src/qa.py`, `src/kpi.py`, `run_pipeline.py`, `README.md` |
| 2. Ghép phần tải/lọc — Claude | Tích hợp `download.py` do thành viên viết, tải và lọc dữ liệu theo tệp phân công. | `src/download.py` |
| 3. Hiểu phương pháp đối chứng và hỗ trợ tạo baseline — Claude | Giải thích cách baseline phân tích review bằng VADER và luật từ khóa, không gọi LLM. | `src/baseline.py` |
| 4. Phân tích review — Gemini API | Trả JSON gồm cảm xúc, ngôn ngữ và danh sách khía cạnh được khen/chê; chỉ dùng 5 khía cạnh đã quy định. | `src/llm.py` |
| 5. Đổi tiêu chí KPI 2 — Codex | Cho phép thêm/bớt tiện nghi trong YAML; listing phải có đủ các tiện nghi đã chọn; đồng bộ QA, công thức, tên KPI và biểu đồ. | `configs/new_york_city.yaml`, `src/utils.py`, `src/qa.py`, `src/kpi.py`, `src/viz.py` |
| 6. Sửa đánh giá — Codex | Chấm sentiment và đủ 10 cột khía cạnh `_positive`/`_negative` cho cả Gemini và baseline; giữ nguyên nhãn tay ( trước evaluate.py chỉ chấm sentiment). | `src/evaluate.py`, `reports/eval_metrics.csv`, `reports/error_analysis.csv` |
| 7. Sửa biểu đồ KPI 2 — Codex | Tách hai ô cho Entire home/apt và Private room; thống nhất màu quận, làm rõ nhãn, tiêu đề và chú giải; giữ đúng số liệu CSV. | `src/viz.py`, `figures/line_amenities.png` |
| 8. Hoàn thiện các hình — Codex | Chỉnh bố cục, màu bản đồ và biểu đồ KPI 4; chọn động khu phố có ít nhất 10 listing giá hợp lệ ở cả 4 mốc, không giới hạn Top 15. | `src/viz.py`, `figures/map_price_borough.png`, `figures/dumbbell_price_change.png` |
| 9. Chạy kiểm tra — Codex | Chạy lại từ filter đến viz bằng dữ liệu và cache có sẵn; báo lỗi/cảnh báo, đối chiếu kết quả và liệt kê đầu ra của pipeline. | `run_pipeline.py`; các bảng trong `data/processed/`, `reports/` và ảnh trong `figures/` |

## AI sai ở đâu

1. **Biểu đồ ban đầu khó đọc:** Claude gộp hai KPI trong một ảnh, chú thích và cách minh họa chưa rõ. Nhóm xem ảnh đầu ra, yêu cầu Codex bố trí lại từng KPI, bổ sung tiêu đề/chú giải và tách KPI 2 theo hai loại phòng trong `src/viz.py`.
2. **Code đánh giá bỏ sót khía cạnh:** bản `evaluate.py` cũ tìm cột như `cleanliness`, trong khi nhãn tay dùng `cleanliness_positive` và `cleanliness_negative`. Pipeline vẫn chạy nhưng chỉ chấm sentiment. Nhóm đối chiếu tên cột, hỏi lại logic rồi yêu cầu sửa cách đọc/chấm; báo cáo hiện có **22 dòng = 11 nhãn × 2 hệ thống**.
3. **Gemini vẫn phân loại sai review:** ví dụ với `review_id=85599711`, review vừa khen việc nhận phòng/khu vực an toàn, vừa chê vệ sinh và giá trị so với giá tiền. Nhãn tay là `mixed`, Gemini dự đoán `negative`. Trường hợp này được ghi trong `reports/error_analysis.csv`; nhóm dùng nhãn tay để đánh giá sai số.

## Nhóm kiểm chứng thế nào

- **Hỏi và đối chiếu code:** dùng Codex/ChatGPT để giải thích công thức, mẫu số, trạng thái T/F/U và cách xử lý dữ liệu thiếu; sau đó kiểm tra lại ở hàm tương ứng và CSV đầu ra.
- **Kiểm tra KPI 2:** đã chạy 13 kiểm thử trong `tests/test_kpi2.py`, gồm đổi tiêu chí, amenities lỗi, mẫu số bằng 0 và tránh nhận nhầm tiện nghi. Với bộ `[wifi, kitchen]`, đối chiếu đủ 41 dòng ở 4 mốc với kết quả cũ; đã thử cả bộ 8 tiêu chí và kiểm tra báo cáo QA cùng tên biểu đồ cập nhật theo.
- **Chạy lại pipeline:** chạy từ filter đến viz với `--skip-llm`, dùng cache Gemini cho 1.000 review. Kiểm tra đủ 7 KPI, 11 ảnh PNG và `reports/qa_report.csv`; lần chạy đã hoàn tất, không có trạng thái QA `blocked`, vẫn ghi nhận các cảnh báo dữ liệu.
- **Đánh giá bằng nhãn tay:** đối chiếu Gemini và baseline với **150 review trong `data/samples/hand_labels.csv`** trên sentiment và 10 cột khía cạnh. Đây là số mẫu thực tế được chấm; tệp phân công đánh dấu 100 review nhãn tay. Xem accuracy, macro-F1 trong `reports/eval_metrics.csv` và đọc các trường hợp sai trong `reports/error_analysis.csv`.
- **Kiểm tra hình:** mở ảnh để rà tiêu đề, đơn vị, màu, chú giải và nhãn chồng nhau; đối chiếu các điểm/giá trị với CSV KPI, không dùng số liệu từ ảnh minh họa.
