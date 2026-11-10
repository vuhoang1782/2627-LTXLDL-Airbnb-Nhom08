"""
Tạo tệp check_<Mã dữ liệu>.csv (Phần 1) và in số liệu để trả lời Phần 2.

Chạy SAU khi loc_du_lieu_airbnb.py đã chạy xong (cần thư mục filtered/).
Chạy trong cùng thư mục project:
    & "C:\\Users\\vuhoang\\miniconda3\\python.exe" tao_bao_cao_kiem_tra.py
"""

from pathlib import Path

import pandas as pd

# ======================= CẤU HÌNH =======================
MA_DU_LIEU = "DSE2049-C04-G08-new-york-city"
MOCS = ["2025-09-01", "2025-12-04", "2026-03-16", "2026-06-14"]
DATA_DIR = Path("data")      # tệp .csv.gz gốc đã tải (để lấy dung lượng)
FILTERED_DIR = Path("filtered")  # dữ liệu đã lọc (để đếm dòng, cột...)
# =========================================================

COT_CSV = [
    "ma_du_lieu", "moc", "ngay", "tai_ve_ok",
    "listings_bytes", "calendar_bytes", "reviews_bytes",
    "listings_dong", "calendar_dong", "reviews_dong",
    "entire_home", "private_room", "khong_co_review", "thieu_price",
    "so_cot_listings", "so_cot_nan_90",
]

rows = []
cau2 = []   # số review Mẫu LLM / Nhãn tay mỗi mốc
cau3 = {}   # tên cột listings >= 90% NaN mỗi mốc

for stt, moc in enumerate(MOCS, start=1):
    # --- Dung lượng 3 tệp gốc đã tải (byte) ---
    goc = {t: DATA_DIR / moc / f"{t}.csv.gz" for t in ["listings", "calendar", "reviews"]}
    tai_ok = "co" if all(p.exists() for p in goc.values()) else "khong"
    size = {t: (p.stat().st_size if p.exists() else "") for t, p in goc.items()}

    # --- Dữ liệu đã lọc ---
    folder = FILTERED_DIR / moc
    listings = pd.read_csv(folder / "listings.csv.gz", low_memory=False)
    # analysis_area là cột do NHÓM tự thêm, không thuộc tệp gốc -> bỏ ra
    # để số cột và số cột NaN phản ánh đúng tệp listings của Inside Airbnb.
    listings = listings.drop(columns=["analysis_area"])
    calendar = pd.read_csv(folder / "calendar.csv.gz", usecols=["listing_id"])
    reviews = pd.read_csv(folder / "reviews.csv.gz")

    room = listings["room_type"].value_counts()
    if "price" in listings.columns:
        thieu_price = int(listings["price"].isna().sum())
    else:
        thieu_price = len(listings)  # không có cột price = thiếu hết
        print(f"[!] Mốc {moc}: listings không có cột price")

    ty_le_nan = listings.isna().mean()           # tỉ lệ NaN của từng cột
    cot_nan_90 = ty_le_nan[ty_le_nan >= 0.9].index.tolist()
    cau3[moc] = cot_nan_90

    rows.append({
        "ma_du_lieu": MA_DU_LIEU,
        "moc": stt,
        "ngay": moc,
        "tai_ve_ok": tai_ok,
        "listings_bytes": size["listings"],
        "calendar_bytes": size["calendar"],
        "reviews_bytes": size["reviews"],
        "listings_dong": len(listings),
        "calendar_dong": len(calendar),
        "reviews_dong": len(reviews),
        "entire_home": int(room.get("Entire home/apt", 0)),
        "private_room": int(room.get("Private room", 0)),
        "khong_co_review": int((listings["number_of_reviews"] == 0).sum()),
        "thieu_price": thieu_price,
        "so_cot_listings": listings.shape[1],
        "so_cot_nan_90": len(cot_nan_90),
    })

    n_llm = int(reviews["mau_llm"].sum())
    n_tay = int(reviews["nhan_tay"].sum())
    tay_ngoai_llm = int((reviews["nhan_tay"] & ~reviews["mau_llm"]).sum())
    cau2.append((moc, n_llm, n_tay, tay_ngoai_llm))

# --- Ghi tệp CSV nộp bài ---
ten_tep = f"check_{MA_DU_LIEU}.csv"
pd.DataFrame(rows, columns=COT_CSV).to_csv(ten_tep, index=False)
print(f"Đã ghi {ten_tep}\n")
print(open(ten_tep, encoding="utf-8").read())

# --- Số liệu cho Phần 2 ---
print("=== Câu 2: số review Mẫu LLM / Nhãn tay tìm được (cần 1000 / 100) ===")
for moc, n_llm, n_tay, ngoai in cau2:
    print(f"  {moc}: Mẫu LLM = {n_llm}, Nhãn tay = {n_tay}, "
          f"nhãn tay nằm ngoài mẫu LLM = {ngoai} (cần 0)")

print("\n=== Câu 3: cột listings có >= 90% NaN, theo từng mốc ===")
for moc, cols in cau3.items():
    print(f"  {moc} ({len(cols)} cột): {', '.join(cols) if cols else '(không có)'}")
