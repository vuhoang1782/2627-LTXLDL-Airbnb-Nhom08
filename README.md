# Inside Airbnb: quy trình phân tích thị trường Airbnb của một thành phố

Môn Lập trình xử lý dữ liệu (UET.DSE2049), HK1 2026-2027. Nhóm 8, lớp UET.DSE2049 4, thành phố New York City.
Quy trình tải dữ liệu Inside Airbnb (CC BY 4.0, https://insideairbnb.com), kiểm tra chất lượng (QA), tính 7 KPI,
phân tích review bằng LLM (Gemini) và vẽ hình, **chạy bằng một lệnh**.

## 1. Cài đặt

Python **3.13.12**, đúng phiên bản ghi trong `.python-version` đã được kiểm thử.

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## 2. Khoá API (chỉ cần cho bước LLM)

Các lệnh bên dưới dùng `--skip-llm`: đọc kết quả đã lưu trong cache, không gọi API và không cần `.env` hay khoá API.
Cache đi kèm đã có kết quả Gemini cho 1.000 review của cấu hình New York City hiện tại.

Nếu cần gọi API cho review chưa có trong cache, bỏ `--skip-llm`, sao chép `.env.example` thành `.env` và điền khoá
**`GEMINI_API_KEY`** hợp lệ (tên biến đổi được ở `llm.api_key_env` trong config). Tên model ở `llm.model`
cần dùng được với khoá đó. Không commit `.env`.

## 3. Chạy

**Không có raw, dùng dữ liệu đã lọc trong `data/interim/`:**

```
python run_pipeline.py --config configs/new_york_city.yaml --start-from qa --skip-llm
```

Các bước: `qa` → `llm` (cache) → `qa_post` → `kpi` → `baseline` → `evaluate` → `viz`.
Nếu không truyền `--start-from` hoặc `--steps`, mặc định cũng chạy từ `qa` đến `viz`.

**Đã có raw của đủ các mốc trong `data/raw/`, chạy lại từ bước lọc:**

```
python run_pipeline.py --config configs/new_york_city.yaml --start-from filter --skip-llm
```

Các bước: `filter` → `qa` → `llm` (cache) → `qa_post` → `kpi` → `baseline` → `evaluate` → `viz`.
Cả hai cách đều không chạy `download`. Khi không có raw, bước `evaluate` vẫn chấm nhãn tay nhưng bỏ qua
việc tính lại ước tính chi phí toàn thành phố; `llm_cost_estimate.csv` đã lưu vẫn được giữ nguyên.

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--start-from qa` | từ QA đến viz, dùng interim đã có; đây là mặc định |
| `--start-from filter` | từ filter đến viz, cần raw đã có |
| `--steps qa,kpi` | chỉ chạy các bước liệt kê |
| `--skip-download` | bỏ download nếu bước này được chọn trong `--steps`; hai chế độ trên vốn không chạy download |
| `--skip-llm` | không gọi API, chỉ dùng cache `data/processed/llm_cache.jsonl` |
| `--llm-limit 20` | chỉ xử lý 20 review đầu (chạy thử rẻ) |

Chọn một trong `--start-from` và `--steps`, không dùng cả hai cùng lúc.
Bước tải và lọc cũng chạy riêng được: `python -m src.download --config configs/new_york_city.yaml [--download-only | --filter-only]`.

## 4. Chạy với thành phố hoặc mốc khác

Thành phố và mốc **chỉ nằm trong tệp cấu hình**, không ghi cứng trong mã. Sao chép `configs/new_york_city.yaml`,
sửa các dòng có `[ĐỔI]` (`city`, `data_root`, `currency`, `snapshots`, `group`, `assignments`, `stakeholder`).
Khi đã có raw phù hợp với cấu hình mới, chạy:

```
python run_pipeline.py --config configs/<thanh_pho>.yaml --start-from filter
```

- Không có mục `assignments` thì quy trình lấy mẫu ngẫu nhiên cố định theo `seed` (listing, review, mẫu LLM, nhãn tay).
- Mốc nào dùng cho KPI nào chọn bằng `kpi.kpi1_snapshot_index`, `kpi3_snapshot_index`, `llm_snapshot_index`.

## 5. Cấu trúc thư mục

```
configs/<thanh_pho>.yaml     cấu hình của thành phố
data/raw/<mốc>/              dữ liệu thô tải về (KHÔNG commit)
data/interim/<mốc>/          dữ liệu đã lọc theo ID của nhóm: <bảng>_filtered.csv.gz
data/processed/              dữ liệu sạch <bảng>_clean.csv.gz, kpi_*.csv, kết quả LLM
data/samples/                tệp phân công ID và tệp nhãn tay
src/                         download, qa, llm, baseline, evaluate, kpi, viz, utils
figures/  reports/           hình và báo cáo sinh tự động
run_pipeline.py              một lệnh chạy cả quy trình
```

## 6. Tệp kết quả để đối chiếu

| Tệp | Nội dung |
|---|---|
| `reports/qa_report.csv` | mỗi quy tắc QA: tên, điều kiện, lý do, hành động, số ảnh hưởng, số hợp lệ, trạng thái, và KPI trước/sau |
| `data/processed/<mốc>/*_clean.csv.gz` | dữ liệu sau QA (giữ cột gốc, thêm cột dẫn xuất và cờ) |
| `data/processed/kpi_01_*.csv` … `kpi_07_*.csv` | bảng 7 KPI; `kpi_definitions.csv` mô tả tên, mục tiêu, công thức, đơn vị |
| `data/processed/kpi_03_listing_level.csv` | trạng thái T/F/U của từng listing cho KPI 3 |
| `data/processed/llm_predictions.csv.gz`, `llm_clean.csv.gz` | kết quả LLM thô và sau QA10 |
| `data/processed/baseline_predictions.csv.gz` | phương pháp đối chứng không dùng LLM |
| `reports/eval_metrics.csv`, `error_analysis.csv` | accuracy/F1 của LLM và baseline so với nhãn tay; các review sai |
| `reports/llm_cost_estimate.csv` | ước tính chi phí xử lý hết review của thành phố |
| `figures/*.png` | hình không gian, thời gian, LLM |

## 7. Nguyên tắc QA (tóm tắt, chi tiết trong `src/qa.py`)

- Không sửa dữ liệu thô và dữ liệu đã lọc; chỉ thêm cột dẫn xuất và cờ. Không `dropna` toàn bảng, không tự điền dữ liệu thiếu.
- Không có một cờ lỗi loại dòng khỏi mọi KPI: **KPI nào cần trường nào thì chỉ KPI đó bỏ dòng thiếu trường ấy**.
- Thiếu, sai định dạng, sai miền và chưa xác định (`U`) được phân biệt. Bản trùng hoàn toàn chỉ tính một lần; cùng khoá nhưng khác nội dung bị gắn `conflict` và không dùng.
- Mẫu số bằng 0 cho `NaN`, không phải 0%.

## 8. Nhãn tay

Tệp `data/samples/hand_labels.csv` hiện có 150 review được gán nhãn tay, gồm `review_id`, `sentiment`
và các cặp cột `<aspect>_positive`, `<aspect>_negative` cho 5 aspect: `cleanliness`, `host_friendliness`,
`noise`, `amenities`, `location`. Mỗi cột dùng 0/1:

| `_positive` | `_negative` | Ý nghĩa |
|---|---|---|
| 0 | 0 | Không có tín hiệu khen hoặc chê về aspect |
| 1 | 0 | Có khen |
| 0 | 1 | Có chê |
| 1 | 1 | Vừa khen vừa chê |

`evaluate` chấm riêng từng cột nhị phân cho Gemini và baseline. Ô trống của cột aspect được hiểu là 0;
review thiếu kết quả dự đoán được ghi là `missing`, không coi là 0. Với tệp hiện tại, `eval_metrics.csv`
có 22 dòng: (sentiment + 10 cột aspect) x 2 hệ thống, mỗi dòng chấm trên 150 review.
`error_analysis.csv` ghi review sai, cột nhãn, nhãn tay, kết quả hai hệ thống và nội dung review.
Cột `language` là tuỳ chọn; chưa có cột này trong nhãn tay thì chưa chấm ngôn ngữ.

`review_id` phải còn nguyên 19 chữ số (Google Sheets/Excel hay làm tròn số dài). Chưa có tệp nhãn tay
thì bước `evaluate` bỏ qua chấm điểm, chỉ ước tính chi phí nếu có raw.

## 9. Tự kiểm tra trước khi nộp

Tải đúng nhánh `codex/pipeline-evaluate-aspects`, dựng môi trường theo mục 1, chọn lệnh ở mục 3 phù hợp
với dữ liệu đang có rồi đối chiếu số liệu, hình với báo cáo. Chạy bằng cache với `--skip-llm` không cần khoá API.
