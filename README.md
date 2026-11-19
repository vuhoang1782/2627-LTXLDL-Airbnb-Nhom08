# Inside Airbnb: quy trình phân tích thị trường Airbnb của một thành phố

Môn Lập trình xử lý dữ liệu (UET.DSE2049), HK1 2026-2027. Nhóm 8, lớp UET.DSE2049 4, thành phố New York City.
Quy trình tải dữ liệu Inside Airbnb (CC BY 4.0, https://insideairbnb.com), kiểm tra chất lượng (QA), tính 7 KPI,
phân tích review bằng LLM (Gemini) và vẽ hình, **chạy bằng một lệnh**.

## 1. Cài đặt

Python phiên bản ghi trong `.python-version`.

```
python -m venv .venv
.venv\Scripts\activate            # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## 2. Khoá API (chỉ cần cho bước LLM)

Sao chép `.env.example` thành `.env` và điền khoá, hoặc đặt biến môi trường **`GEMINI_API_KEY`**
(tên biến đổi được ở `llm.api_key_env` trong config). Mã chỉ đọc khoá từ biến môi trường, không ghi khoá vào mã.
Khoá bất kỳ đều chạy được. Tên model ở `llm.model` trong config, cần là model còn dùng được với khoá đó.

## 3. Chạy

```
python run_pipeline.py --config configs/new_york_city.yaml
```

Các bước (theo thứ tự): `download` → `filter` → `qa` → `llm` → `qa_post` → `kpi` → `baseline` → `evaluate` → `viz`.

| Tuỳ chọn | Ý nghĩa |
|---|---|
| `--steps qa,kpi` | chỉ chạy các bước liệt kê |
| `--skip-download` | bỏ bước tải (đã có `data/raw`) |
| `--skip-llm` | không gọi API, chỉ dùng cache `data/processed/llm_cache.jsonl` |
| `--llm-limit 20` | chỉ xử lý 20 review đầu (chạy thử rẻ) |

Bước tải và lọc cũng chạy riêng được: `python -m src.download --config configs/new_york_city.yaml [--download-only | --filter-only]`.

## 4. Chạy với thành phố hoặc mốc khác

Thành phố và mốc **chỉ nằm trong tệp cấu hình**, không ghi cứng trong mã. Sao chép `configs/new_york_city.yaml`,
sửa các dòng có `[ĐỔI]` (`city`, `data_root`, `currency`, `snapshots`, `group`, `assignments`, `stakeholder`) rồi chạy:

```
python run_pipeline.py --config configs/<thanh_pho>.yaml
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

Đặt tệp `data/samples/hand_labels.csv` (cột `review_id` + `sentiment`, `language` và/hoặc tên aspect; ô aspect trống = review không nhắc tới).
`review_id` phải còn nguyên 19 chữ số (Google Sheets/Excel hay làm tròn số dài). Chưa có tệp thì bước `evaluate` chỉ ước tính chi phí.

## 9. Tự kiểm tra trước khi nộp

Clone vào thư mục mới, dựng môi trường theo mục 1, đặt khoá theo mục 2, chạy lệnh ở mục 3 và đối chiếu số liệu, hình
với báo cáo.
