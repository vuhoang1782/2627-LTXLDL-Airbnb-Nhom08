Dưới đây là tệp `AI_USAGE.md` được biên tập lại để khớp **100% với bản phân công chính thức** bạn vừa gửi, đồng thời bổ sung chính xác các chi tiết kỹ thuật và con số thực tế từ bộ mã nguồn Bản 2 (`baseline_2.py`, `download_2.py`, `evaluate_2.py`, `kpi_2.py`, `llm_2.py`, `qa_2.py`, `viz_2.py`, `utils_2.py`) mà không làm thay đổi cấu trúc công cụ hay nội dung đã chốt của nhóm:

---

# AI_USAGE.md

## Công cụ đã dùng (vào việc gì)

* **Claude (Anthropic):** xây dựng khung và mã nguồn chính ban đầu (`src/`, `run_pipeline.py`, cấu hình), tạo các bước xuất `reports/`, `figures/`; hỗ trợ soạn `README.md`, `AI_USAGE.md`, `requirements.txt` và các tệp thiết lập dự án.
* **Codex:** chỉnh KPI 2 theo mục đích mới (chuyển sang cấu hình động qua `qa.amenity_rules` và `kpi.kpi2_required_amenities`) và cập nhật QA liên quan; sửa `src/viz.py` để biểu đồ dễ đọc; chỉnh cấu hình, README, thư viện và tối ưu code. Hỗ trợ sửa phần đánh giá (`src/evaluate.py` chấm đồng thời nhãn gộp và từng cột `_positive`/`_negative`), chạy thử pipeline, phát hiện lỗi và viết báo cáo.


* **Gemini API (gói miễn phí):** được gọi trong `src/llm.py` để phân tích cảm xúc, khía cạnh khen/chê và ngôn ngữ của review; lưu kết quả vào `llm_cache.jsonl` để chạy lại bằng cache với cờ `--skip-llm`.


* **ChatGPT:** hỗ trợ lên ý tưởng, lập kế hoạch KPI/QA, soạn prompt, giải thích code và số liệu báo cáo, gợi ý lệnh commit.

Nhóm tự đọc review và gán nhãn tay theo quy ước chung; không lấy dự đoán AI làm nhãn chuẩn. Nhóm chịu trách nhiệm rà soát và lựa chọn nội dung đưa vào bài nộp.

## Prompt then chốt (5–10): bước nào, vào tệp nào

Dưới đây là **9 prompt được tóm tắt ý chính** theo đúng tiến trình thực hiện của nhóm, không phải bản chép nguyên văn lịch sử chat.

| Bước / công cụ | Nội dung yêu cầu chính | Tệp áp dụng hoặc đầu ra |
| --- | --- | --- |
| 1. Khởi tạo — Claude | Xây dựng project theo đề bài, bộ 10 quy tắc QA (`QA01`–`QA10`, giữ nguyên dữ liệu gốc và gắn cờ `analysis_row`, `T`/`F`/`U`) và 7 KPI; ưu tiên code đơn giản, dễ giải thích.

 | `src/qa.py`, `src/kpi.py`, `src/utils.py`, `run_pipeline.py`, `README.md` |
| 2. Ghép phần tải/lọc — Claude | Tích hợp `download.py` do thành viên viết, tải 4 mốc dữ liệu và lọc theo tệp phân công của nhóm (`Lớp`, `Nhóm`, `Mẫu LLM`, `Nhãn tay`) ra tầng trung gian `data/interim/`.

 | `src/download.py` |
| 3. Hiểu phương pháp đối chứng — Claude | Giải thích và chuẩn hóa cách baseline phân tích review bằng VADER theo mệnh đề (`CLAUSE`), từ khóa khía cạnh và từ dừng ngôn ngữ mà không gọi LLM.

 | `src/baseline.py` |
| 4. Phân tích review — Gemini API | Trả về mảng JSON gồm `sentiment`, `language` và hai danh sách `aspects_positive`, `aspects_negative`; chỉ dùng 5 khía cạnh đã quy định và dùng chỉ số lô cục bộ (`id`) để tránh sai lệch ID 19 chữ số.

 | Prompt trong `src/llm.py`; `data/processed/llm_predictions.csv.gz` |
| 5. Đổi tiêu chí KPI 2 — Codex | Cho phép thêm/bớt tiện nghi trong YAML (`qa.amenity_rules`); listing phải có đủ các tiện nghi đã chọn (phép AND); gắn mã băm SHA-256 (`amenity_rules_hash`) để đồng bộ QA, công thức, tên KPI và biểu đồ.

 | `configs/new_york_city.yaml`, `src/utils.py`, `src/qa.py`, `src/kpi.py`, `src/viz.py` |
| 6. Sửa đánh giá — Codex | Chấm `sentiment` và đủ 10 cột khía cạnh `_positive`/`_negative` (cùng nhãn khía cạnh gộp) cho cả Gemini và baseline; giữ nguyên nhãn tay.

 | `src/evaluate.py`, `reports/eval_metrics.csv`, `reports/error_analysis.csv` |
| 7. Sửa biểu đồ KPI 2 — Codex | Tách hai ô (`Entire home/apt` và `Private room`) với thang Y độc lập; thống nhất màu quận, dàn nhãn đầu/cuối tránh chồng chéo, làm rõ tiêu đề và chú giải; giữ đúng số liệu CSV.

 | `src/viz.py`, `figures/line_amenities.png` |
| 8. Hoàn thiện các hình — Codex | Chỉnh bố cục, màu bản đồ choropleth và biểu đồ quả tạ KPI 4; chọn động khu phố có ít nhất 10 listing giá hợp lệ ở cả 4 mốc, tự chia đôi hình nếu quá dài thay vì giới hạn cứng Top 15.

 | `src/viz.py`, `figures/map_price_borough.png`, `figures/dumbbell_price_change.png` |
| 9. Chạy kiểm tra — Codex | Chạy lại từ bước lọc đến trực quan hóa bằng dữ liệu và cache có sẵn (`--skip-llm`); báo lỗi/cảnh báo, đối chiếu kết quả và liệt kê đầu ra của pipeline.

 | `run_pipeline.py`; các bảng trong `data/processed/`, `reports/` và ảnh trong `figures/` |

## AI sai ở đâu (ví dụ thật)

1. **Biểu đồ ban đầu khó đọc:** Claude gộp hai KPI trong một ảnh, chú thích và cách minh họa chưa rõ, nhãn tỷ lệ trên biểu đồ đường bị đè lên nhau. Nhóm xem ảnh đầu ra, yêu cầu Codex bố trí lại từng KPI, bổ sung tiêu đề/chú giải, thêm thuật toán đẩy khoảng cách nhãn theo trục Y và tách KPI 2 theo hai loại phòng trong `src/viz.py`.


2. **Code đánh giá bỏ sót khía cạnh:** Bản `evaluate.py` cũ chỉ tìm cột gộp như `cleanliness`, trong khi tệp nhãn tay gán chi tiết theo 10 cột `cleanliness_positive` và `cleanliness_negative`. Pipeline vẫn chạy nhưng không chấm chi tiết từng chiều khen/chê. Nhóm đối chiếu tên cột, hỏi lại logic rồi yêu cầu sửa cách đọc/chấm trong `src/evaluate.py`; báo cáo `eval_metrics.csv` hiện chấm đầy đủ cả nhãn cảm xúc, nhãn khía cạnh gộp và 10 cột khía cạnh đơn lẻ cho cả 2 hệ thống.


3. **Gemini vẫn phân loại sai review hỗn hợp (`mixed`):** Với `review_id=85599711`, review vừa khen việc nhận phòng/khu vực an toàn, vừa chê vệ sinh và giá trị so với giá tiền. Nhãn tay là `mixed`, nhưng Gemini dự đoán `negative`. Trường hợp này được ghi nhận tự động trong `reports/error_analysis.csv`; nhóm dùng tệp nhãn tay độc lập để đánh giá sai số khách quan thay vì tin tuyệt đối vào LLM.


4. **Rủi ro lệch cờ QA khi thay đổi danh mục tiện nghi KPI 2:** Khi chuyển KPI 2 sang danh mục động trong YAML (`qa.amenity_rules`), nếu sửa cấu hình mà chạy thẳng `kpi.py` không qua `qa.py`, số liệu cũ sẽ bị tái sử dụng âm thầm. Nhóm đã bổ sung `validate_amenities_config()` và `amenity_rules_hash()` trong `src/utils.py` để `kpi.py` tự động chặn và báo lỗi nếu phát hiện mã băm quy tắc không khớp.



## Nhóm kiểm chứng thế nào

* **Hỏi và đối chiếu code:** Dùng Codex/ChatGPT để giải thích công thức, mẫu số, trạng thái 3 giá trị `T`/`F`/`U` và cách xử lý dữ liệu thiếu (mẫu số bằng 0 trả về `NaN` thay vì `0%`); sau đó kiểm tra lại trực tiếp ở hàm tương ứng trong `src/qa.py`, `src/kpi.py` và các CSV đầu ra.


* **Kiểm tra KPI 2:** Đã chạy 13 kiểm thử trong `tests/test_kpi2.py`, gồm đổi tiêu chí tiện nghi, `amenities` lỗi/thiếu (`U`), mẫu số bằng 0 và tránh nhận nhầm tiện nghi. Với bộ `[wifi, kitchen]`, đối chiếu đủ 41 dòng ở 4 mốc với kết quả cũ; đã thử cả bộ 8 tiêu chí và kiểm tra báo cáo `qa_report.csv` cùng tên biểu đồ `line_amenities.png` cập nhật khớp theo metadata.


* **Chạy lại pipeline:** Chạy từ bước lọc (`--filter-only`) đến trực quan hóa (`viz.py`) với cờ `--skip-llm`, dùng cache Gemini cho 1.000 review. Kiểm tra đủ 7 bảng KPI, các ảnh PNG (và HTML tương tác) cùng `reports/qa_report.csv`; lần chạy đã hoàn tất, không có trạng thái QA `blocked`, vẫn ghi nhận đầy đủ các cảnh báo dữ liệu.


* **Đánh giá bằng nhãn tay:** Đối chiếu Gemini và baseline VADER với **150 review trong `data/samples/hand_labels.csv**` (đã kiểm tra không trùng lặp, không bị lỗi làm tròn ID 19 chữ số và khớp `0/150` sai lệch với dữ liệu gốc) trên `sentiment` và 10 cột khía cạnh. Đây là số mẫu thực tế được chấm (tệp phân công đánh dấu 100 review nhãn tay). Xem `accuracy`, `macro_f1` trong `reports/eval_metrics.csv` và đọc chi tiết các trường hợp sai kèm trích đoạn bình luận trong `reports/error_analysis.csv`.


* **Kiểm tra hình:** Mở từng ảnh trong `figures/` để rà tiêu đề tiếng Việt, đơn vị, bảng màu, chú giải và tình trạng nhãn chồng nhau; đối chiếu trực tiếp các con số hiển thị trên biểu đồ với bảng CSV KPI tương ứng, không lấy số liệu từ ảnh minh họa.
