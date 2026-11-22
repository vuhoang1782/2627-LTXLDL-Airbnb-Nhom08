# Inside Airbnb: phân tích thị trường New York City

Nhóm 8, lớp UET.DSE2049 4, HK1 2026–2027. Project kiểm tra chất lượng dữ liệu,
tính 7 KPI, phân tích review bằng Gemini, so sánh với baseline và vẽ biểu đồ.

## 1. Cài gì?

Cài **Git** và **Python 3.13.12** (phiên bản đã kiểm thử), sau đó clone nhánh `main`:

```bash
git clone --branch main https://github.com/vuhoang1782/2627-LTXLDL-Airbnb-Nhom08.git
cd 2627-LTXLDL-Airbnb-Nhom08
python -m venv .venv
```

Kích hoạt môi trường theo terminal đang dùng:

- Windows PowerShell: `.\.venv\Scripts\Activate.ps1`
- Windows CMD: `.venv\Scripts\activate.bat`
- Linux/macOS: `source .venv/bin/activate`

Cài thư viện:

```bash
python -m pip install -r requirements.txt
```

## 2. Chạy lệnh nào?

Chạy các lệnh dưới đây tại thư mục gốc repo. Chọn cách phù hợp với dữ liệu đang có.

### Cách 1: dùng dữ liệu đã lọc và cache LLM có sẵn

Đây là cách chạy ban đầu, giữ nguyên `--skip-llm`:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa --skip-llm
```

Lệnh dùng dữ liệu đã lọc trong `data/interim/` và cache Gemini cho 1.000 review để tạo lại
dữ liệu sạch, 7 KPI, kết quả đánh giá và biểu đồ. File bản đồ
`data/raw/2026-06-14/neighbourhoods.geojson` được cung cấp kèm repo; không cần tải các CSV thô.

### Cách 2: bắt đầu từ filter khi đã có đủ raw

Chuẩn bị đủ `listings.csv.gz`, `calendar.csv.gz` và `reviews.csv.gz` trong từng thư mục
`data/raw/<mốc>/`. Với config hiện tại, cần đủ cả 4 mốc: `2025-09-01`, `2025-11-01`,
`2026-03-16` và `2026-06-14`. Giữ hai tệp phân công `data/samples/listing_ids.csv` và
`data/samples/review_ids.csv` theo mục `assignments` trong config.

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from filter --skip-llm
```

Lệnh lọc lại raw theo ID được phân công, ghi dữ liệu vào `data/interim/`, rồi chạy tiếp
QA, LLM từ cache, KPI, baseline, đánh giá và biểu đồ. Bước tải dữ liệu không chạy;
`--skip-llm` vẫn giữ nguyên như cách 1.

### Cách 3: chạy lại từ LLM khi chưa có hoặc còn thiếu kết quả LLM

Chuẩn bị API key theo mục 3. Nếu đã chạy bước `qa` và có dữ liệu sạch trong
`data/processed/<mốc>/` (đặc biệt `reviews_clean.csv.gz` ở mốc LLM, hiện là `2026-06-14`), chạy:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --steps llm,qa_post,kpi,baseline,evaluate,viz
```

Lệnh gọi Gemini cho các review chưa có cache, kiểm tra kết quả bằng `qa_post`, rồi cập nhật
KPI, baseline, đánh giá và biểu đồ. Review đã có cache khớp ID, nội dung, provider và model
được dùng lại; chạy lại sau khi gián đoạn sẽ tiếp tục phần còn thiếu.

Nếu chỉ có dữ liệu đã lọc và chưa chạy QA, chạy từ QA để tạo cả dữ liệu sạch lẫn kết quả LLM:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa
```

Nếu bắt đầu từ raw và cũng cần gọi Gemini, dùng lệnh ở cách 2 nhưng bỏ `--skip-llm`.
Nếu chỉ thiếu file `llm_predictions.csv.gz` mà cache đã đủ, thêm `--skip-llm` vào lệnh
`--steps` ở trên để tạo lại kết quả từ cache. Khi cache chưa đủ, `--skip-llm` chỉ cảnh báo
review thiếu kết quả, không tự gọi API để bổ sung.

### Đổi tiêu chí KPI 2

KPI 2 yêu cầu listing có **đủ tất cả** tiện nghi được chọn. Trong
`configs/new_york_city.yaml`, sửa `kpi.kpi2_required_amenities`, ví dụ thêm máy giặt:

```yaml
kpi2_required_amenities: [wifi, kitchen, washer]
```

Các lựa chọn và quy tắc nhận diện nằm trong phần `qa.amenity_rules` của config.
Sau khi đổi, chạy lại lệnh ở cách 1 để QA cập nhật cờ tiện nghi trước khi tính KPI.

## 3. Có cần API key không?

**Không cần** khi chạy với `--skip-llm`: project dùng kết quả trong `data/processed/llm_cache.jsonl`.
Để có đầy đủ kết quả LLM, cache phải đủ cho mẫu review và model đang cấu hình.

Để gọi Gemini cho review chưa có cache, sao chép `.env.example` thành `.env`, điền
`GEMINI_API_KEY`, kiểm tra tên model tại `llm.model` trong config và dùng lệnh ở cách 3
không có `--skip-llm`.
Không commit `.env`.

## 4. Xem kết quả ở đâu?

Khi log xuất hiện `Xong viz`, quy trình đã chạy xong.

| Đường dẫn | Nội dung |
|---|---|
| `figures/*.png` | Biểu đồ KPI, bản đồ và so sánh Gemini với baseline |
| `data/processed/kpi_*.csv` | Bảng KPI và định nghĩa cách tính |
| `data/processed/<mốc>/*_clean.csv.gz` | Dữ liệu sau kiểm tra chất lượng |
| `data/processed/llm_cache.jsonl` | Cache Gemini để dùng lại và tiếp tục review còn thiếu |
| `data/processed/llm_predictions.csv.gz` | Kết quả phân tích review bằng LLM trước bước `qa_post` |
| `data/processed/llm_clean.csv.gz` | Kết quả LLM sau QA để tính KPI 6, 7 |
| `reports/qa_report.csv` | Báo cáo chất lượng dữ liệu |
| `reports/eval_metrics.csv` | Accuracy, macro-F1 của Gemini và baseline so với nhãn tay |
| `reports/error_analysis.csv` | Các review dự đoán sai để đối chiếu |

Dữ liệu nguồn: [Inside Airbnb](https://insideairbnb.com), giấy phép CC BY 4.0.
