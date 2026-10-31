# Báo cáo kiểm tra dữ liệu DSE2049-C04-G08-new-york-city

New York City · USD. Chỉ lọc ID và gắn analysis_area, chưa cleaning/preprocessing/tính KPI.

## Câu 1. Có tệp nào không tải được hoặc không đọc được?

Cả 12 file CSV.GZ đều tồn tại, giải nén và đọc CSV đến hết thành công. Không tải Internet. Tên file thực tế có hậu tố YYMMDD, không đổi tên file nguồn.

`tai_ve_ok=co` xác nhận đủ 3 file cục bộ đọc được; `khong` khi thiếu/lỗi. Không suy đoán HTTP. Dung lượng byte là của file gzip nguồn.

| Mốc | Listings nguồn (byte) | Calendar nguồn (byte) | Reviews nguồn (byte) | Cột nguồn L/C/R |
|---|---:|---:|---:|---|
| 2025-09-01 | 17809878 | 30746999 | 118206134 | 79/7/6 |
| 2025-12-04 | 18328158 | 31711038 | 119705158 | 85/7/6 |
| 2026-03-16 | 17574953 | 29347960 | 121109311 | 90/5/6 |
| 2026-06-14 | 15694632 | 25904041 | 119440985 | 90/5/6 |

Schema đầy đủ, tên nguồn thực tế, SHA-256, số dòng nguồn và mọi kiểm tra được lưu trong `validation_details.json`.

## Câu 2. Tìm được bao nhiêu review mẫu LLM và nhãn tay?

| Snapshot | LLM thực tế / 1.000 | Nhãn tay thực tế / 100 |
|---|---:|---:|
| 2025-09-01 | 1000 | 100 |
| 2025-12-04 | 1000 | 100 |
| 2026-03-16 | 1000 | 100 |
| 2026-06-14 | 1000 | 100 |

Số ID đánh dấu mẫu LLM trong config: **PASS**, thực tế 1000, kỳ vọng 1000.

Số ID đánh dấu nhãn tay trong config: **PASS**, thực tế 100, kỳ vọng 100.

Số ID nhãn tay nằm ngoài tập LLM: **PASS**, thực tế 0, kỳ vọng 0.

Lọc reviews theo `reviews.id`; không tạo nhãn, không gọi API.

## Câu 3. Các cột listings có ít nhất 90% NaN

Tính trên số dòng listings thực tế sau lọc, loại analysis_area. Dùng cơ chế NA mặc định của Pandas trên bản đọc chẩn đoán: ô rỗng là NA, số 0 không phải NA. Khi ghi interim vẫn giữ nguyên chuỗi gốc, kể cả chuỗi NA/NULL.

### 2025-09-01: 1 cột / 1000 dòng

| Cột | Số NaN | Tỷ lệ |
|---|---:|---:|
| calendar_updated | 1000 | 100.00% |

### 2025-12-04: 3 cột / 1000 dòng

| Cột | Số NaN | Tỷ lệ |
|---|---:|---:|
| price | 1000 | 100.00% |
| calendar_updated | 1000 | 100.00% |
| estimated_revenue_l365d | 1000 | 100.00% |

### 2026-03-16: 12 cột / 1000 dòng

| Cột | Số NaN | Tỷ lệ |
|---|---:|---:|
| neighborhood_overview | 1000 | 100.00% |
| host_since | 1000 | 100.00% |
| host_response_time | 1000 | 100.00% |
| host_response_rate | 1000 | 100.00% |
| host_acceptance_rate | 1000 | 100.00% |
| host_thumbnail_url | 1000 | 100.00% |
| host_neighbourhood | 1000 | 100.00% |
| host_total_listings_count | 1000 | 100.00% |
| host_verifications | 1000 | 100.00% |
| neighbourhood | 1000 | 100.00% |
| calendar_updated | 1000 | 100.00% |
| instant_bookable | 1000 | 100.00% |

### 2026-06-14: 12 cột / 1000 dòng

| Cột | Số NaN | Tỷ lệ |
|---|---:|---:|
| neighborhood_overview | 1000 | 100.00% |
| host_since | 1000 | 100.00% |
| host_response_time | 1000 | 100.00% |
| host_response_rate | 1000 | 100.00% |
| host_acceptance_rate | 1000 | 100.00% |
| host_thumbnail_url | 1000 | 100.00% |
| host_neighbourhood | 1000 | 100.00% |
| host_total_listings_count | 1000 | 100.00% |
| host_verifications | 1000 | 100.00% |
| neighbourhood | 1000 | 100.00% |
| calendar_updated | 1000 | 100.00% |
| instant_bookable | 1000 | 100.00% |

## Câu 4. Cột dự kiến dùng cho KPI/phân tích có bị rỗng không?

Đây là đánh giá sơ bộ vì nhóm chưa xác định KPI chính thức. Kiểm tra giá, availability, loại phòng, review, khu vực và thời gian; chưa tính KPI. Bảng ghi `số thiếu/tổng số dòng`; `VẮNG CỘT` khác với `100% RỖNG`. Cột đầy đủ ở mọi mốc vẫn được liệt kê để đối chiếu.

### listings

| Cột | 2025-09-01 | 2025-12-04 | 2026-03-16 | 2026-06-14 |
|---|---|---|---|---|
| price | 92/1000 | 1000/1000 (100% RỖNG) | 61/1000 | 20/1000 |
| price_quote_price_per_night | VẮNG CỘT | VẮNG CỘT | 61/1000 | 20/1000 |
| price_quote_total_price | VẮNG CỘT | VẮNG CỘT | 61/1000 | 20/1000 |
| price_quote_checkin_date | VẮNG CỘT | VẮNG CỘT | 54/1000 | 16/1000 |
| price_quote_checkout_date | VẮNG CỘT | VẮNG CỘT | 54/1000 | 16/1000 |
| estimated_revenue_l365d | 92/1000 | 1000/1000 (100% RỖNG) | 61/1000 | 20/1000 |
| estimated_occupancy_l365d | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| calendar_updated | 1000/1000 (100% RỖNG) | 1000/1000 (100% RỖNG) | 1000/1000 (100% RỖNG) | 1000/1000 (100% RỖNG) |
| has_availability | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| instant_bookable | 0/1000 | 0/1000 | 1000/1000 (100% RỖNG) | 1000/1000 (100% RỖNG) |
| availability_30 | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| availability_60 | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| availability_90 | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| availability_365 | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| room_type | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| number_of_reviews | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| number_of_reviews_ltm | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| number_of_reviews_l30d | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| reviews_per_month | 50/1000 | 30/1000 | 25/1000 | 25/1000 |
| review_scores_rating | 50/1000 | 30/1000 | 25/1000 | 25/1000 |
| first_review | 50/1000 | 30/1000 | 25/1000 | 25/1000 |
| last_review | 50/1000 | 30/1000 | 25/1000 | 25/1000 |
| analysis_area | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| neighbourhood_cleansed | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| neighbourhood_group_cleansed | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| latitude | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| longitude | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| host_since | 4/1000 | 2/1000 | 1000/1000 (100% RỖNG) | 1000/1000 (100% RỖNG) |
| last_scraped | 0/1000 | 0/1000 | 0/1000 | 0/1000 |
| calendar_last_scraped | 0/1000 | 0/1000 | 0/1000 | 0/1000 |

### calendar

| Cột | 2025-09-01 | 2025-12-04 | 2026-03-16 | 2026-06-14 |
|---|---|---|---|---|
| listing_id | 0/365000 | 0/365000 | 0/365000 | 0/365000 |
| date | 0/365000 | 0/365000 | 0/365000 | 0/365000 |
| available | 0/365000 | 0/365000 | 0/365000 | 0/365000 |
| price | 365000/365000 (100% RỖNG) | 365000/365000 (100% RỖNG) | VẮNG CỘT | VẮNG CỘT |
| adjusted_price | 365000/365000 (100% RỖNG) | 365000/365000 (100% RỖNG) | VẮNG CỘT | VẮNG CỘT |
| minimum_nights | 0/365000 | 0/365000 | 0/365000 | 0/365000 |
| maximum_nights | 0/365000 | 0/365000 | 0/365000 | 0/365000 |

### reviews

| Cột | 2025-09-01 | 2025-12-04 | 2026-03-16 | 2026-06-14 |
|---|---|---|---|---|
| id | 0/5000 | 0/5000 | 0/5000 | 0/5000 |
| listing_id | 0/5000 | 0/5000 | 0/5000 | 0/5000 |
| date | 0/5000 | 0/5000 | 0/5000 | 0/5000 |
| comments | 0/5000 | 0/5000 | 0/5000 | 0/5000 |

Đề xuất: chỉ dùng `listings.price` tại **2026-06-14** theo yêu cầu giảng viên; giữ và báo cáo các giá thiếu, không tự điền. Không dùng cột hoàn toàn rỗng cho snapshot đó. Với cột chỉ có ở một số mốc, giới hạn phân tích ở các mốc có dữ liệu hoặc cân nhắc cột khác sau khi xác minh ý nghĩa. Calendar thiếu price/adjusted_price thì không dùng chúng cho phân tích giá tại mốc tương ứng. Cột thiếu một phần phải nêu số mẫu hợp lệ và quy tắc xử lý trong giai đoạn sau; hiện tại giữ nguyên toàn bộ dữ liệu.

## Câu 5. Dữ liệu đủ để làm hay cần cấp lại?

**Dữ liệu đủ để tiếp tục bước tiếp theo**: tất cả kiểm tra bắt buộc PASS; đủ tập ID, số dòng, phân bổ loại phòng/vùng và tiêu chí đặc thù từng mốc. Các cột thiếu vẫn được giữ nguyên và cần áp dụng giới hạn sử dụng nêu ở Câu 4.

| Snapshot | Listings / 1.000 | Calendar / 365.000 | Reviews / 5.000 | Không review | Thiếu price |
|---|---:|---:|---:|---:|---:|
| 2025-09-01 | 1000 | 365000 | 5000 | 50 | 92 |
| 2025-12-04 | 1000 | 365000 | 5000 | 30 | 1000 |
| 2026-03-16 | 1000 | 365000 | 5000 | 25 | 61 |
| 2026-06-14 | 1000 | 365000 | 5000 | 25 | 20 |

Các ID/cặp ngày bất thường và giá trị thực tế/kỳ vọng của cả PASS lẫn FAIL xem `validation_details.json`. Kiểm tra cùng tập ID giữa bốn mốc chạy độc lập với kiểm tra đúng tập phân công.

ID được giữ nguyên dạng chuỗi. Kiểm tra được định dạng và so khớp chính xác với raw; không thể chứng minh lịch sử làm tròn trước khi nhận config chỉ bằng một chuỗi chữ số. ID không tìm thấy được liệt kê, không tự khôi phục hay làm tròn.

Đối chiếu SHA-256 toàn bộ file raw/config/processed trước và sau chạy được lưu trong JSON. Không ghi dữ liệu vào processed. Hash từng ô của các dòng chọn từ nguồn khớp hash đọc lại interim, kiểm tra cả thứ tự dòng và cột.

Chạy lại tại thư mục project:

```powershell
.\.venv\Scripts\python.exe .\scripts\filter_and_check.py
```

Mã thoát 0 = tất cả PASS; 1 = đã xuất báo cáo với FAIL; 2 = lỗi thực thi ngoài dự kiến.
