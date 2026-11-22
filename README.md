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

Tại thư mục gốc repo, chạy:

```bash
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa --skip-llm
```

Lệnh dùng dữ liệu đã lọc trong `data/interim/` và cache Gemini cho 1.000 review để tạo lại
dữ liệu sạch, 7 KPI, kết quả đánh giá và biểu đồ. File bản đồ
`data/raw/2026-06-14/neighbourhoods.geojson` được cung cấp kèm repo; không cần tải các CSV thô.

### Đổi tiêu chí KPI 2

KPI 2 yêu cầu listing có **đủ tất cả** tiện nghi được chọn. Trong
`configs/new_york_city.yaml`, sửa `kpi.kpi2_required_amenities`, ví dụ thêm máy giặt:

```yaml
kpi2_required_amenities: [wifi, kitchen, washer]
```

Các lựa chọn và quy tắc nhận diện nằm trong phần `qa.amenity_rules` của config.
Sau khi đổi, chạy lại lệnh ở trên.

## 3. Có cần API key không?

**Không cần** khi chạy với `--skip-llm`: project dùng kết quả trong `data/processed/llm_cache.jsonl`.

Để gọi Gemini cho review chưa có cache, sao chép `.env.example` thành `.env`, điền
`GEMINI_API_KEY`, kiểm tra tên model tại `llm.model` trong config và bỏ `--skip-llm` khỏi lệnh chạy.
Không commit `.env`.

## 4. Xem kết quả ở đâu?

Khi log xuất hiện `Xong viz`, quy trình đã chạy xong.

| Đường dẫn | Nội dung |
|---|---|
| `figures/*.png` | Biểu đồ KPI, bản đồ và so sánh Gemini với baseline |
| `data/processed/kpi_*.csv` | Bảng KPI và định nghĩa cách tính |
| `data/processed/<mốc>/*_clean.csv.gz` | Dữ liệu sau kiểm tra chất lượng |
| `reports/qa_report.csv` | Báo cáo chất lượng dữ liệu |
| `reports/eval_metrics.csv` | Accuracy, macro-F1 của Gemini và baseline so với nhãn tay |
| `reports/error_analysis.csv` | Các review dự đoán sai để đối chiếu |

Dữ liệu nguồn: [Inside Airbnb](https://insideairbnb.com), giấy phép CC BY 4.0.
