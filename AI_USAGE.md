# AI_USAGE.md

## Công cụ đã dùng

- **ChatGPT:** hỗ trợ lên ý tưởng, phản biện và hoàn thiện 10 quy tắc QA, 7 KPI do nhóm đề xuất; hỗ trợ thống nhất công thức, điều kiện tính, cách xử lý dữ liệu thiếu, soạn prompt, giải thích code, chọn thêm 50 nhãn tay và kiểm tra nhãn tay sau khi gán.
- **Claude:** hỗ trợ xây dựng cấu trúc project, triển khai mã nguồn theo quy tắc QA và KPI đã thống nhất, tích hợp các bước xử lý dữ liệu, LLM, baseline.
- **Codex:** hỗ trợ điều chỉnh KPI 2 và QA liên quan, hoàn thiện phần đánh giá và trực quan hóa, tối ưu code, cập nhật cấu hình, README và kiểm tra pipeline.
- **Gemini API (gói miễn phí):** sử dụng trong `src/llm.py` để phân tích cảm xúc, ngôn ngữ và các khía cạnh được khen/chê trong review; lưu kết quả vào cache để dùng lại khi khớp review ID, nội dung, provider và model.

Nhóm thảo luận và quyết định phương án cuối cùng, tự gán nhãn tay theo quy ước chung và chịu trách nhiệm kiểm tra mã nguồn, số liệu và kết quả của project.

## Prompt then chốt

*Các prompt dưới đây được tóm tắt từ nội dung yêu cầu đã sử dụng trong quá trình thực hiện project, không phải bản chép nguyên văn toàn bộ lịch sử trao đổi.*

| Bước / công cụ | Nội dung yêu cầu chính | Tệp áp dụng hoặc đầu ra |
|---|---|---|
| 1. Hoàn thiện quy tắc QA — ChatGPT | Phản biện và hoàn thiện 10 quy tắc QA từ đề xuất của nhóm; thống nhất cách kiểm tra dữ liệu thiếu, sai định dạng, trùng lặp và ngoại lai; giữ dữ liệu gốc, ưu tiên gắn cờ hợp lệ. | `src/qa.py`, `configs/new_york_city.yaml` |
| 2. Hoàn thiện phương án KPI — ChatGPT | Rà soát 7 KPI do nhóm đề xuất; thống nhất công thức, tử số, mẫu số, đơn vị, mốc dữ liệu và điều kiện hợp lệ sau QA; xử lý trường hợp mẫu số bằng 0. | `src/kpi.py`, `configs/new_york_city.yaml` |
| 3. Khởi tạo pipeline và tích hợp tải/lọc dữ liệu — Claude | Xây dựng cấu trúc project, hỗ trợ đọc cấu hình, bảo toàn ID khi đọc CSV, tích hợp tải và lọc dữ liệu theo tệp phân công; tổ chức các bước chạy pipeline. | `src/utils.py`, `src/download.py`, `run_pipeline.py` |
| 4. Triển khai QA và KPI — Claude | Viết code theo 10 quy tắc QA và 7 KPI nhóm đã thống nhất; chuẩn hóa dữ liệu, tạo cờ hợp lệ, tính KPI và ghi nhận tác động trước/sau QA. | `src/qa.py`, `src/kpi.py`, `reports/qa_report.csv` |
| 5. Tích hợp LLM và hậu kiểm — Claude | Tích hợp Gemini API, đọc JSON và kiểm tra ID, số kết quả trong lô; bảo toàn review ID, lưu cache và triển khai QA10 để kiểm tra kết quả LLM trước khi tính KPI. | `src/llm.py`, `src/qa.py`, `data/processed/llm_cache.jsonl`, `data/processed/llm_clean.csv.gz` |
| 6. Phân tích review — Gemini API | Phân loại cảm xúc thành `positive`, `negative`, `mixed`; xác định ngôn ngữ và các khía cạnh được khen/chê trong 5 khía cạnh đã quy định; trả kết quả theo cấu trúc JSON. | `src/llm.py`, `data/processed/llm_predictions.csv.gz` |
| 7. Xây dựng baseline — Claude | Giải thích và triển khai phương pháp đối chứng bằng VADER kết hợp luật từ khóa, không gọi LLM; chuẩn hóa đầu ra để so sánh với Gemini. | `src/baseline.py` |
| 8. Điều chỉnh KPI 2 — Codex | Cho phép cấu hình danh sách tiện nghi trong YAML; kiểm tra listing có đủ tất cả tiện nghi đã chọn; đồng bộ quy tắc QA, cách tính KPI và tên biểu đồ. | `configs/new_york_city.yaml`, `src/utils.py`, `src/qa.py`, `src/kpi.py`, `src/viz.py` |
| 9. Hoàn thiện đánh giá — Codex | Chấm sentiment và đủ 10 cột khía cạnh `_positive`/`_negative` cho cả Gemini và baseline; đối chiếu với nhãn tay độc lập. | `src/evaluate.py`, `reports/eval_metrics.csv`, `reports/error_analysis.csv` |
| 10. Hoàn thiện trực quan hóa — Codex | Tách KPI 2 thành hai ô cho `Entire home/apt` và `Private room`, dùng thang trục Y riêng; cải thiện biểu đồ KPI 4, bản đồ và các hình khác; điều chỉnh bố cục, màu sắc, tiêu đề và chú thích, giữ nguyên số liệu KPI. | `src/viz.py`, `figures/` |

## AI sai ở đâu

1. **Biểu đồ ban đầu khó đọc:** Claude gộp hai KPI trong một ảnh, một số tiêu đề và chú thích chưa rõ. Nhóm kiểm tra ảnh đầu ra và yêu cầu Codex bố trí lại biểu đồ, bổ sung chú giải, tách KPI 2 theo hai loại phòng và xử lý nhãn chồng nhau trong `src/viz.py`.
2. **Code đánh giá bỏ sót các khía cạnh:** bản `evaluate.py` ban đầu tìm các cột như `cleanliness`, trong khi nhãn tay sử dụng `cleanliness_positive` và `cleanliness_negative`. Pipeline vẫn chạy nhưng chỉ chấm sentiment. Nhóm đối chiếu tên cột và yêu cầu sửa logic đánh giá. Báo cáo sau khi sửa có 22 dòng kết quả (11 nhãn × 2 hệ thống).
3. **Gemini phân loại sai review hỗn hợp:** với `review_id=85599711`, khách vừa khen việc nhận phòng và khu vực an toàn, vừa chê vệ sinh và giá trị so với giá tiền. Nhãn tay là `mixed`, nhưng Gemini dự đoán `negative`. Nhóm ghi nhận sai lệch trong `reports/error_analysis.csv` và sử dụng nhãn tay để đánh giá kết quả LLM.
## Nhóm kiểm chứng thế nào

- **Đối chiếu quy tắc và công thức:** kiểm tra code QA và KPI với phương án nhóm đã thống nhất, đặc biệt là tử số, mẫu số, trạng thái `T`/`F`/`U` và cách xử lý dữ liệu thiếu; đối chiếu kết quả với CSV đầu ra.
- **Chạy lại pipeline:** chạy từ bước `filter` đến `viz` với `--skip-llm`, sử dụng cache Gemini cho 1.000 review. Kiểm tra đầu ra của 7 KPI, 11 ảnh PNG và `reports/qa_report.csv`.
- **Đánh giá bằng nhãn tay:** sử dụng 150 review trong `data/samples/hand_labels.csv`, đều khớp ID với Gemini và baseline; tệp phân công đánh dấu 100 review nhãn tay, còn `evaluate.py` đọc đủ 150 dòng trong tệp nhãn (nhóm quyết định mở rộng nhãn tay một cách ngẫu  để tăng độ đa dạng của đánh giá tay, do 100 nhãn đầu quá lệch về positive, ít negative và mixed, được phát hiện trong quá trình dán nhãn tay). Chấm sentiment và 10 cột khía cạnh. Kết quả sentiment (`accuracy` / `macro_f1`): Gemini **0.8667 / 0.7797**, baseline **0.7733 / 0.7220** trong `reports/eval_metrics.csv`; các trường hợp sai nằm trong `reports/error_analysis.csv`.
- **Kiểm tra biểu đồ:** mở các ảnh trong `figures/` để kiểm tra tiêu đề, đơn vị, màu sắc, chú giải và nhãn chồng nhau; đối chiếu các giá trị hiển thị với bảng CSV KPI tương ứng.
