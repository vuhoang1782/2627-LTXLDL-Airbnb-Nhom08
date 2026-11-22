# Bài tập lớn cuối kỳ — Inside Airbnb: Phân tích thị trường New York City

**Môn học:** Lập trình xử lý dữ liệu (UET.DSE2049), học kỳ 1, năm học 2026–2027.  
**Đề bài chính thức:** [Bài tập lớn Inside Airbnb](https://courses.iaidev.com/programming-for-data-processing/2627-1/projects/project_airbnb.html). Yêu cầu, thời hạn và rubric áp dụng theo thông báo mới nhất trên Canvas.

Project thực hiện tải và lọc dữ liệu theo phân công, kiểm tra chất lượng dữ liệu theo 10 quy tắc QA, tính 7 KPI, phân tích cảm xúc & khía cạnh review bằng Gemini, đối chứng với baseline VADER, đánh giá trên nhãn tay và trực quan hóa biểu đồ/bản đồ.

---

## 1. Thông tin nhóm

- **Mã lớp:** UET.DSE2049 4
- **Tên/mã nhóm:** Nhóm 08
- **Thành phố được phân công:** New York City (tiền tệ USD)
- **Bốn mốc dữ liệu:** `2025-09-01`, `2025-11-01`, `2026-03-16`, `2026-06-14`

| Họ tên | MSSV | GitHub username | Công việc phụ trách |
|---|---|---|---|
| *Nguyễn Quốc Cường* | *25022799* | *cuongnq152-cmd* |  *Thực hiện phần llm.py, download.py, baseline.py và nhãn tay, hỗ trợ code và tối ưu* |
| *(Thành viên 2)* | *(MSSV)* | *(username)* | *(Nhóm điền phân công thực tế)* |
| *(Thành viên 3)* | *(MSSV)* | *(username)* | *(Nhóm điền phân công thực tế)* |
| *(Thành viên 4)* | *(MSSV)* | *(username)* | *(Nhóm điền phân công thực tế)* |
| *(Thành viên 5)* | *(MSSV)* | *(username)* | *(Nhóm điền phân công thực tế)* |

> **Lưu ý vấn đáp:** Mỗi thành viên cần nắm rõ và giải thích được toàn bộ quy trình xử lý dữ liệu, quy tắc QA, công thức KPI và kết quả đánh giá của nhóm.

---

## 2. Cài đặt môi trường

Cài **Git** và **Python 3.13.12** (phiên bản đã kiểm thử), sau đó clone nhánh `main`:

```bash
git clone --branch main [https://github.com/vuhoang1782/2627-LTXLDL-Airbnb-Nhom08.git](https://github.com/vuhoang1782/2627-LTXLDL-Airbnb-Nhom08.git)
cd 2627-LTXLDL-Airbnb-Nhom08
python -m venv .venv

```

Kích hoạt môi trường ảo theo terminal đang dùng:

* **Windows PowerShell:** `.\.venv\Scripts\Activate.ps1`
* **Windows CMD:** `.venv\Scripts\activate.bat`
* **Linux / macOS:** `source .venv/bin/activate`

Cài đặt thư viện:

```bash
python -m pip install -r requirements.txt

```

### Cấu hình API key (chỉ cần khi gọi mới Gemini API)

* **Không cần API key** khi chạy với cờ `--skip-llm`: hệ thống sử dụng trực tiếp kết quả đã lưu trong `data/processed/llm_cache.jsonl`.
* Khi cần gọi Gemini cho các review chưa có trong cache, sao chép tệp mẫu `.env.example` thành `.env`, điền `GEMINI_API_KEY` (hoặc đặt biến môi trường trong terminal) và kiểm tra tên model tại mục `llm.model` trong `configs/new_york_city.yaml`:

```bash
cp .env.example .env
# Mở .env và điền: GEMINI_API_KEY="khoa-api-cua-ban"

```

> **Bảo mật:** Tuyệt đối không ghi khóa thật vào mã nguồn và không commit tệp `.env` (đã được khai báo trong `.gitignore`).

---

## 3. Hướng dẫn chạy Pipeline

Chạy các lệnh dưới đây tại thư mục gốc của repo. Chọn kịch bản phù hợp với dữ liệu đang có:

### Cách 1: Dùng dữ liệu đã lọc và cache LLM có sẵn (Khuyên dùng)

Đây là cách chạy tiêu chuẩn trên repo đã có sẵn dữ liệu lọc và cache:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa --skip-llm

```

Lệnh này sử dụng dữ liệu đã lọc trong `data/interim/` và cache Gemini cho 1.000 review (`data/processed/llm_cache.jsonl`) để tái tạo toàn bộ dữ liệu sạch, 7 KPI, kết quả đối chứng baseline, đánh giá nhãn tay và biểu đồ. Tệp bản đồ `data/raw/2026-06-14/neighbourhoods.geojson` đã được cung cấp kèm repo nên không cần tải lại các tệp CSV thô.

### Cách 2: Bắt đầu từ bước `filter` khi đã có đủ dữ liệu thô (`raw`)

Chuẩn bị đủ `listings.csv.gz`, `calendar.csv.gz` và `reviews.csv.gz` trong từng thư mục `data/raw/<mốc>/` cho cả 4 mốc (`2025-09-01`, `2025-11-01`, `2026-03-16`, `2026-06-14`), đồng thời giữ hai tệp phân công `data/samples/listing_ids.csv` và `data/samples/review_ids.csv` theo mục `assignments` trong config:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from filter --skip-llm

```

Lệnh này đọc theo khối dữ liệu thô, lọc đúng ID phân công của nhóm ghi vào `data/interim/`, sau đó chạy tiếp toàn bộ các bước từ QA đến trực quan hóa.

### Cách 3: Chạy lại bước LLM khi cần gọi bổ sung Gemini API

Sau khi đã thiết lập `GEMINI_API_KEY` trong `.env` và có dữ liệu sạch trong `data/processed/<mốc>/` (đặc biệt là `reviews_clean.csv.gz` ở mốc LLM `2026-06-14`), chạy:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --steps llm,qa_post,kpi,baseline,evaluate,viz

```

* Lệnh chỉ gọi Gemini cho các review chưa có trong `llm_cache.jsonl` (khớp theo `review_id`, `text_hash`, `provider`, `model`); nếu gián đoạn giữa chừng có thể chạy lại để tiếp tục phần còn thiếu.
* Nếu chưa chạy QA trước đó, chạy từ bước `qa` và bỏ `--skip-llm`:
```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa

```


* Nếu chỉ thiếu `llm_predictions.csv.gz` nhưng cache đã đủ, thêm `--skip-llm` vào lệnh `--steps` ở trên để tổng hợp lại từ cache (khi cache thiếu review nào, hệ thống chỉ cảnh báo chứ không gọi API).

### Đổi tiêu chí tiện nghi của KPI 2

KPI 2 yêu cầu listing phải có **đủ tất cả** tiện nghi được chọn (phép `AND`). Mở `configs/new_york_city.yaml` và chỉnh danh sách tại `kpi.kpi2_required_amenities` (ví dụ thêm máy giặt):

```yaml
kpi2_required_amenities: [wifi, kitchen, washer]

```

Các quy tắc nhận diện từng tiện nghi nằm ở mục `qa.amenity_rules`. Sau khi sửa cấu hình, **bắt buộc chạy lại từ bước `qa**` (lệnh ở Cách 1) để cập nhật cờ tiện nghi và mã băm quy tắc (`amenities_rules_hash`) trước khi tính KPI.

---

## 4. Kiến trúc Pipeline & Các bước xử lý

| Bước | Mô-đun | Nhiệm vụ chính | Đầu ra |
| --- | --- | --- | --- |
| 1 | `src/download.py` | Tải 4 mốc × 3 bảng từ Inside Airbnb (kiểm tra gzip, thử lại khi lỗi mạng) và lọc theo ID phân công của nhóm | `data/raw/`, `data/interim/<mốc>/*_filtered.csv.gz` |
| 2 | `src/qa.py` (`pre`) | Kiểm tra 9 quy tắc QA đầu vào (`QA01`–`QA09`): giữ nguyên dữ liệu gốc, gắn cờ `analysis_row`, trạng thái `T`/`F`/`U` | `data/processed/<mốc>/*_clean.csv.gz`, `reports/qa_report.csv` |
| 3 | `src/llm.py` | Phân tích cảm xúc (`positive`/`mixed`/`negative`), ngôn ngữ và 5 khía cạnh khen/chê cho 1.000 review bằng Gemini (có cache JSONL) | `data/processed/llm_cache.jsonl`, `llm_predictions.csv.gz` |
| 4 | `src/baseline.py` | Mô hình đối chứng không dùng LLM: VADER tách mệnh đề đối lập + từ khóa khía cạnh + nhận diện ngôn ngữ | `data/processed/baseline_predictions.csv.gz` |
| 5 | `src/qa.py` (`post`) | Hậu kiểm kết quả LLM (`QA10`): lọc trùng/xung đột, kiểm tra khớp `text_hash` và miền giá trị hợp lệ | `data/processed/llm_clean.csv.gz`, cập nhật `reports/qa_report.csv` |
| 6 | `src/kpi.py` | Tính 7 KPI từ các cờ đã QA (mẫu số 0 → `NaN`), ghi tác động trước/sau QA vào báo cáo kiểm toán | `data/processed/kpi_01_*.csv` – `kpi_07_*.csv`, `kpi_definitions.csv` |
| 7 | `src/evaluate.py` | Chấm `accuracy`, `macro_f1` của Gemini và baseline trên 150 nhãn tay; xuất lỗi sai và ước tính chi phí toàn thành phố | `reports/eval_metrics.csv`, `error_analysis.csv`, `llm_cost_estimate.csv` |
| 8 | `src/viz.py` | Xuất biểu đồ tĩnh (PNG 150 DPI) và tương tác (HTML Plotly) kèm bản đồ không gian bằng tiếng Việt | `figures/*.png`, `figures/*.html` |

---

## 5. Danh mục tệp kết quả để đối chiếu

Khi log xuất hiện `Xong viz`, toàn bộ quy trình đã hoàn tất.

| Đường dẫn | Nội dung |
| --- | --- |
| `figures/*.png`, `figures/*.html` | Biểu đồ 7 KPI, bản đồ phân bố listing/giá theo quận và biểu đồ đối chiếu đánh giá |
| `data/processed/kpi_*.csv` | 7 bảng kết quả KPI và bảng định nghĩa công thức (`kpi_definitions.csv`) |
| `data/processed/<mốc>/*_clean.csv.gz` | Dữ liệu sau kiểm tra chất lượng kèm đầy đủ cờ QA |
| `data/processed/llm_cache.jsonl` | Cache kết quả Gemini để tái lập và chạy tiếp các review còn thiếu |
| `data/processed/llm_predictions.csv.gz` | Kết quả phân tích review từ LLM trước bước hậu kiểm `qa_post` |
| `data/processed/llm_clean.csv.gz` | Kết quả LLM đạt chuẩn sau `QA10` dùng để tính KPI 6 và KPI 7 |
| `reports/qa_report.csv` | Báo cáo kiểm toán 10 quy tắc QA kèm chỉ số tác động `kpi_before` / `kpi_after` |
| `reports/eval_metrics.csv` | Độ chính xác (`accuracy`, `macro_f1`) của Gemini và baseline trên 150 nhãn tay |
| `reports/error_analysis.csv` | Danh sách chi tiết các review dự đoán sai kèm trích đoạn nội dung để phân tích lỗi |
| `reports/llm_cost_estimate.csv` | Ước tính số token và chi phí chạy LLM cho toàn bộ review của thành phố |

---

## 6. Cấu trúc thư mục & Lưu ý kỹ thuật

```text
run_pipeline.py              # Điểm chạy điều phối toàn bộ pipeline
configs/new_york_city.yaml   # Cấu hình thành phố, mốc thời gian, quy tắc tiện nghi KPI 2, tham số LLM/QA
src/                         # Mã nguồn: utils, download, qa, llm, baseline, kpi, evaluate, viz
data/
  ├── raw/                   # Dữ liệu thô từ Inside Airbnb (không commit, trừ neighbourhoods.geojson)
  ├── interim/               # Dữ liệu đã lọc theo ID phân công của nhóm
  ├── processed/             # Dữ liệu sạch sau QA, cache/kết quả LLM, baseline và 7 bảng KPI
  └── samples/               # Tệp phân công (listing_ids.csv, review_ids.csv) và nhãn tay (hand_labels.csv)
reports/                     # Báo cáo QA, kết quả chấm điểm đánh giá, phân tích lỗi và ước tính chi phí
figures/                     # Biểu đồ và bản đồ xuất ra (PNG & HTML)
AI_USAGE.md                  # Tài liệu minh bạch việc sử dụng công cụ AI

```

> **Cảnh báo bảo toàn ID 19 chữ số:** Các cột `id`, `listing_id`, `review_id` trong bộ dữ liệu có độ dài lên tới 19 chữ số. **Không mở và lưu đè trực tiếp các tệp CSV (đặc biệt là `data/samples/hand_labels.csv`) bằng Microsoft Excel** vì Excel sẽ tự động làm tròn thành dạng số khoa học (`E+`), làm hỏng khóa đối chiếu. Hãy chỉnh sửa bằng VS Code / trình soạn thảo văn bản thuần, hoặc chọn định dạng cột là **Text** khi nhập dữ liệu.

---

## 7. Quy trình nộp bài

Sau khi hoàn tất mã nguồn, báo cáo và `AI_USAGE.md`, đẩy commit cuối lên nhánh `main` và gắn tag `final` theo yêu cầu đề bài:

```bash
git tag final
git push origin final
git rev-parse final          # Ghi mã commit SHA này vào báo cáo nộp bài

```

Dữ liệu nguồn: [Inside Airbnb](https://insideairbnb.com), giấy phép CC BY 4.0.

```

*(Lưu ý: Bạn nhớ điền bổ sung thông tin họ tên, MSSV, GitHub username và công việc phụ trách của các thành viên nhóm 08 vào bảng ở **Mục 1** trước khi commit nhé).*

```
