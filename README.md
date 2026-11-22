# Inside Airbnb: Phân tích thị trường New York City

Bài tập lớn cuối kỳ môn **Lập trình xử lý dữ liệu**, học kỳ 1, năm học 2026–2027.
Dự án kiểm tra chất lượng dữ liệu theo 10 quy tắc QA, tính 7 KPI, phân tích đánh giá
của khách bằng Gemini, so sánh với baseline VADER và trực quan hóa kết quả.

## Thông tin nhóm

- **Lớp:** UET.DSE2049 4
- **Nhóm:** 08
- **Thành phố:** New York City
- **Đơn vị tiền tệ:** USD
- **Bốn mốc dữ liệu:** `2025-09-01`, `2025-11-01`, `2026-03-16`, `2026-06-14`

| STT | Họ và tên | MSSV | GitHub | Vai trò |
| --- | --- | --- | --- | --- |
| 1 | Lâm Tuấn Đạt | 25022819 | `datthichai05-ai` | Nhóm trưởng |
| 2 | Nguyễn Quốc Cường | 25022799 | `cuongnq152-cmd` | Thành viên |
| 3 | Phạm Thế Dương | 25022814 | `25022814-lang` | Thành viên |
| 4 | Hoàng Tấn Anh Vũ | 25023076 | `vuhoang1782` | Thành viên |
| 5 | Lưu Gia Bình | 25022794 | `bmu3` | Thành viên |

Mẫu được phân công gồm 1.000 listing và 5.000 review, trong đó 1.000 review dùng
cho LLM và 100 review được đánh dấu nhãn tay. Nhóm mở rộng tập nhãn tay lên 150
review để đánh giá Gemini và baseline. Kết quả phân tích được diễn giải trong
phạm vi mẫu, phục vụ tư vấn lưu trú ngắn hạn tại New York City.

## Cài đặt môi trường

Cài **Git** và **Python 3.13.12** (phiên bản đã kiểm thử), sau đó chạy:

```bash
git clone --branch main https://github.com/vuhoang1782/2627-LTXLDL-Airbnb-Nhom08.git
cd 2627-LTXLDL-Airbnb-Nhom08
python -m venv .venv
```

Kích hoạt môi trường ảo theo terminal đang dùng:

| Terminal | Lệnh |
| --- | --- |
| Windows PowerShell | `.\.venv\Scripts\Activate.ps1` |
| Windows CMD | `.venv\Scripts\activate.bat` |
| Linux / macOS | `source .venv/bin/activate` |

Cài đặt thư viện:

```bash
python -m pip install -r requirements.txt
```

Để xuất thêm biểu đồ HTML tương tác, cài Plotly (tùy chọn):

```bash
python -m pip install plotly
```

### Cấu hình Gemini API

Khi chạy với `--skip-llm`, dự án chỉ đọc cache trong
`data/processed/llm_cache.jsonl` và không cần API key. Cache phải khớp mẫu review,
nội dung, provider và model đang cấu hình để tạo đủ kết quả.

Để gọi Gemini cho review chưa có cache:

1. Sao chép `.env.example` thành `.env` tại thư mục gốc.
2. Điền khóa vào biến `GEMINI_API_KEY` trong `.env`.
3. Kiểm tra tên model tại `llm.model` trong `configs/new_york_city.yaml`.
4. Chạy pipeline không có `--skip-llm` theo hướng dẫn bên dưới.

Tệp `.env` đã được khai báo trong `.gitignore`; không đưa API key vào mã nguồn.

## Chạy pipeline

Chạy các lệnh tại thư mục gốc của repo. Chọn cách phù hợp với dữ liệu đang có.

### 1. Dùng dữ liệu đã lọc và cache có sẵn

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa --skip-llm
```

Lệnh đọc dữ liệu trong `data/interim/` và cache Gemini cho 1.000 review để tạo lại
dữ liệu sạch, 7 KPI, kết quả baseline, đánh giá và biểu đồ. GeoJSON được cung cấp
tại `data/raw/2026-06-14/neighbourhoods.geojson`, nên không cần tải CSV thô để chạy
cách này. Bước ước tính chi phí chỉ được tính lại khi có dữ liệu reviews thô.

### 2. Lọc lại khi đã có đủ dữ liệu thô

Chuẩn bị `listings.csv.gz`, `calendar.csv.gz` và `reviews.csv.gz` trong từng thư mục
`data/raw/<mốc>/` cho cả bốn mốc dữ liệu. Giữ hai tệp phân công
`data/samples/listing_ids.csv` và `data/samples/review_ids.csv` theo mục
`assignments` trong cấu hình.

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from filter --skip-llm
```

Lệnh lọc dữ liệu theo ID được phân công vào `data/interim/`, sau đó chạy tiếp từ
QA đến trực quan hóa. Bước tải dữ liệu không được chạy trong lệnh này.

### 3. Bổ sung kết quả Gemini

Sau khi cấu hình API key và có dữ liệu sạch từ bước `qa`, chạy:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --steps llm,qa_post,kpi,baseline,evaluate,viz
```

Dữ liệu đầu vào LLM là `data/processed/2026-06-14/reviews_clean.csv.gz` theo cấu hình
hiện tại. Hệ thống chỉ gọi API cho review chưa có cache khớp `review_id`,
`text_hash`, `provider` và `model`; có thể chạy lại để tiếp tục khi bị gián đoạn.

Nếu chưa chạy QA, bắt đầu từ dữ liệu đã lọc:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa
```

Nếu bắt đầu từ dữ liệu thô và cần gọi Gemini, bỏ `--skip-llm` ở cách 2. Nếu cache
đã đủ nhưng thiếu `llm_predictions.csv.gz`, thêm `--skip-llm` vào lệnh `--steps`
ở cách 3 để tạo lại tệp từ cache. Khi thiếu cache, cờ này chỉ ghi cảnh báo và không
gọi API bổ sung.

### Cấu hình tiện nghi cho KPI 2

KPI 2 yêu cầu listing có **đủ tất cả** tiện nghi được chọn. Danh sách hiện tại nằm
tại `kpi.kpi2_required_amenities` trong `configs/new_york_city.yaml`:

```yaml
kpi:
  kpi2_required_amenities: [wifi, kitchen, washer]
```

Các khóa tiện nghi và quy tắc nhận diện được định nghĩa trong `qa.amenity_rules`.
Sau khi thay đổi danh sách hoặc quy tắc, chạy lại từ bước `qa` như cách 1 để cập
nhật cờ tiện nghi và `amenities_rules_hash` trước khi tính KPI.

## Các bước xử lý

| Bước | Mô-đun | Nội dung |
| --- | --- | --- |
| `download` | `src/download.py` | Tải dữ liệu thô vào `data/raw/`; chỉ chạy khi được chọn rõ bằng `--steps download`. |
| `filter` | `src/download.py` | Lọc theo ID phân công, ghi dữ liệu vào `data/interim/<mốc>/`. |
| `qa` | `src/qa.py` | Kiểm tra QA01–QA09, chuẩn hóa và gắn cờ hợp lệ cho dữ liệu đầu vào. |
| `llm` | `src/llm.py` | Phân tích cảm xúc, ngôn ngữ và 5 khía cạnh review bằng Gemini; lưu cache JSONL. |
| `qa_post` | `src/qa.py` | Hậu kiểm QA10: ID, nội dung, trùng lặp, xung đột và miền giá trị của kết quả LLM. |
| `kpi` | `src/kpi.py` | Tính 7 KPI và ghi tác động trước/sau QA vào báo cáo. |
| `baseline` | `src/baseline.py` | Phân tích review bằng VADER kết hợp luật từ khóa để đối chứng. |
| `evaluate` | `src/evaluate.py` | Đánh giá trên nhãn tay, xuất các lỗi dự đoán và ước tính chi phí LLM khi có dữ liệu thô. |
| `viz` | `src/viz.py` | Xuất biểu đồ và bản đồ PNG; bổ sung HTML khi có Plotly. |

Pipeline mặc định chạy từ `qa` đến `viz`. Dùng `--start-from filter` khi cần lọc
lại dữ liệu thô, hoặc `--steps` để chọn các bước cụ thể theo thứ tự thực hiện.

## Tệp kết quả

Khi log xuất hiện `Xong viz`, lệnh chạy đến bước trực quan hóa đã hoàn tất.

| Đường dẫn | Nội dung |
| --- | --- |
| `figures/*.png` | Biểu đồ 7 KPI, bản đồ và so sánh Gemini với baseline. |
| `figures/*.html` | Biểu đồ tương tác, chỉ xuất khi có Plotly. |
| `data/processed/kpi_01_*.csv` – `kpi_07_*.csv` | Kết quả 7 KPI. |
| `data/processed/kpi_definitions.csv` | Định nghĩa, công thức và đơn vị của các KPI. |
| `data/processed/<mốc>/*_clean.csv.gz` | Dữ liệu sau QA kèm các cờ hợp lệ. |
| `data/processed/llm_cache.jsonl` | Cache Gemini để tái sử dụng và tiếp tục xử lý. |
| `data/processed/llm_predictions.csv.gz` | Kết quả LLM trước hậu kiểm. |
| `data/processed/llm_clean.csv.gz` | Kết quả LLM sau QA10 dùng cho KPI 6 và KPI 7. |
| `data/processed/baseline_predictions.csv.gz` | Kết quả phân tích của baseline. |
| `reports/qa_report.csv` | Báo cáo QA và tác động `kpi_before` / `kpi_after`. |
| `reports/eval_metrics.csv` | Accuracy và macro-F1 của Gemini và baseline trên nhãn tay. |
| `reports/error_analysis.csv` | Các dự đoán sai kèm nhãn tay và trích đoạn review. |
| `reports/llm_cost_estimate.csv` | Ước tính token và chi phí cho toàn bộ review thành phố; cần reviews thô để tính lại. |

## Cấu trúc thư mục

```text
.
├── README.md
├── run_pipeline.py            # Điều phối pipeline
├── requirements.txt          # Thư viện Python
├── .env.example              # Mẫu cấu hình API key
├── configs/
│   └── new_york_city.yaml    # Cấu hình dữ liệu, QA, KPI và LLM
├── src/                      # Mã nguồn các bước xử lý
├── data/
│   ├── raw/                  # Dữ liệu thô; repo chỉ lưu GeoJSON
│   ├── interim/              # Dữ liệu đã lọc theo ID phân công
│   ├── processed/            # Dữ liệu sạch, cache, kết quả LLM, baseline và KPI
│   └── samples/              # Tệp phân công và hand_labels.csv
├── reports/                  # Báo cáo QA, đánh giá và phân tích lỗi
├── figures/                  # Biểu đồ và bản đồ
├── report.pdf                # Báo cáo tổng hợp
└── AI_USAGE.md               # Khai báo sử dụng công cụ AI
```

**Bảo toàn ID:** Các cột `id`, `listing_id`, `review_id` có thể dài tới 19 chữ số.
Khi nhập CSV vào Excel hoặc Google Sheets, đặt các cột này ở dạng **Text** để
tránh làm tròn. Với `data/samples/hand_labels.csv`, nên chỉnh bằng trình soạn thảo
văn bản và giữ nguyên `review_id` để đối chiếu kết quả.

## Tài liệu và nguồn dữ liệu

- [Báo cáo tổng hợp](report.pdf)
- [Khai báo sử dụng công cụ AI](AI_USAGE.md)
- [Đề bài môn học](https://courses.iaidev.com/programming-for-data-processing/2627-1/projects/project_airbnb.html)
- [Inside Airbnb](https://insideairbnb.com) — nguồn dữ liệu, giấy phép CC BY 4.0.
