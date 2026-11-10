"""
Lọc dữ liệu Inside Airbnb cho UET.DSE2049 - Lớp 4 - Nhóm 8 (New York City).

Cấu trúc thư mục mong đợi (sửa ở phần CẤU HÌNH nếu của bạn khác):

    project/
      loc_du_lieu_airbnb.py
      listing_ids.csv          <- tab «Listing» tải từ Google Sheets
      review_ids.csv           <- tab «Review»  tải từ Google Sheets
      data/
        2025-09-01/  listings.csv.gz  calendar.csv.gz  reviews.csv.gz
        2025-12-04/  (3 tệp)
        2026-03-16/  (3 tệp)
        2026-06-14/  (3 tệp)

Kết quả được ghi vào thư mục filtered/<mốc>/.
"""

from pathlib import Path

import pandas as pd

# ======================= CẤU HÌNH =======================
LOP = "UET.DSE2049 4"
NHOM = 8
MOCS = ["2025-09-01", "2025-12-04", "2026-03-16", "2026-06-14"]

DATA_DIR = Path("data")
LISTING_IDS_CSV = Path("listing_ids.csv")
REVIEW_IDS_CSV = Path("review_ids.csv")
OUT_DIR = Path("filtered")

CHUNKSIZE = 500_000  # số dòng đọc mỗi khối (giảm nếu máy yếu)
CALENDAR_COLS = ["listing_id", "date", "available", "price"]  # chỉ đọc cột cần

# Số liệu kiểm tra do đề bài cho
EXPECTED_ZERO_REVIEWS = [50, 30, 25, 25]  # theo thứ tự 4 mốc
# =========================================================


def read_id_lists():
    """Đọc 2 danh sách ID và giữ lại đúng dòng của nhóm."""
    # ID rất dài (tới 19 chữ số) -> ép int64 để không bị làm tròn thành số thực
    lst = pd.read_csv(LISTING_IDS_CSV, dtype={"listing_id": "int64"})
    rev = pd.read_csv(
        REVIEW_IDS_CSV, dtype={"review_id": "int64", "listing_id": "int64"}
    )

    # Phải khớp đồng thời Lớp VÀ Nhóm
    lst = lst[(lst["Lớp"] == LOP) & (lst["Nhóm"] == NHOM)].copy()
    rev = rev[(rev["Lớp"] == LOP) & (rev["Nhóm"] == NHOM)].copy()

    print(f"Số listing ID của nhóm: {len(lst)}  (cần 1000)")
    print(f"Số review ID của nhóm : {len(rev)}  (cần 5000)")
    assert len(lst) == 1000 and lst["listing_id"].is_unique, "Danh sách listing sai"
    assert len(rev) == 5000 and rev["review_id"].is_unique, "Danh sách review sai"
    return lst, rev


def filter_listings(path, lst):
    df = pd.read_csv(path, low_memory=False)
    df = df[df["id"].isin(lst["listing_id"])].copy()
    # Gắn vùng phân tích: id -> analysis_area
    df["analysis_area"] = df["id"].map(lst.set_index("listing_id")["analysis_area"])
    return df


def filter_in_chunks(path, id_column, keep_ids, usecols=None):
    """Đọc tệp lớn theo từng khối, lọc ngay trong khối, rồi ghép kết quả."""
    kept = []
    for chunk in pd.read_csv(path, chunksize=CHUNKSIZE, usecols=usecols):
        kept.append(chunk[chunk[id_column].isin(keep_ids)])
    return pd.concat(kept, ignore_index=True)


def filter_reviews(path, rev):
    df = filter_in_chunks(path, "id", set(rev["review_id"]))
    info = rev.set_index("review_id")
    df["mau_llm"] = df["id"].map(info["Mẫu LLM"]).eq("x")
    df["nhan_tay"] = df["id"].map(info["Nhãn tay"]).eq("x")
    return df


def check_moc(i, moc, listings, calendar, reviews):
    print(f"\n--- Kiểm tra mốc {moc} ---")
    ok = True

    def report(name, value, expected):
        nonlocal ok
        good = value == expected
        ok &= good
        print(f"  [{'OK ' if good else 'SAI'}] {name}: {value} (cần {expected})")

    report("số dòng listings", len(listings), 1000)
    report("số dòng calendar", len(calendar), 365_000)
    report("số dòng reviews", len(reviews), 5000)

    rt = listings["room_type"].value_counts()
    report("Entire home/apt", int(rt.get("Entire home/apt", 0)), 875)
    report("Private room", int(rt.get("Private room", 0)), 125)

    zero = int((listings["number_of_reviews"] == 0).sum())
    report("listing có number_of_reviews = 0", zero, EXPECTED_ZERO_REVIEWS[i])

    if i == len(MOCS) - 1:
        report("listing thiếu price (mốc cuối)", int(listings["price"].isna().sum()), 20)

    per_area = listings["analysis_area"].value_counts()
    good = per_area.between(120, 130).all() and len(per_area) == 8
    ok &= good
    print(f"  [{'OK ' if good else 'SAI'}] số listing mỗi vùng (cần 120-130): "
          f"{per_area.sort_index().to_dict()}")
    return ok


def main():
    lst, rev = read_id_lists()
    listing_ids = set(lst["listing_id"])
    all_ok = True

    for i, moc in enumerate(MOCS):
        print(f"\n===== Xử lý mốc {moc} =====")
        folder = DATA_DIR / moc

        listings = filter_listings(folder / "listings.csv.gz", lst)
        # usecols dạng hàm: cột nào có trong tệp thì lấy, thiếu thì bỏ qua
        # (một số mốc của Inside Airbnb không có cột price trong calendar)
        calendar = filter_in_chunks(
            folder / "calendar.csv.gz",
            "listing_id",
            listing_ids,
            usecols=lambda c: c in CALENDAR_COLS,
        )
        thieu = [c for c in CALENDAR_COLS if c not in calendar.columns]
        if thieu:
            print(f"  Lưu ý: calendar mốc {moc} không có cột {thieu}")
        reviews = filter_reviews(folder / "reviews.csv.gz", rev)

        all_ok &= check_moc(i, moc, listings, calendar, reviews)

        out = OUT_DIR / moc
        out.mkdir(parents=True, exist_ok=True)
        listings.to_csv(out / "listings.csv.gz", index=False)
        calendar.to_csv(out / "calendar.csv.gz", index=False)
        reviews.to_csv(out / "reviews.csv.gz", index=False)

    print("\nTẤT CẢ KHỚP" if all_ok else "\nCÓ CHỖ SAI - xem các dòng [SAI] ở trên")


if __name__ == "__main__":
    main()
