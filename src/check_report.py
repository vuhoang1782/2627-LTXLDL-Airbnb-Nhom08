"""Bước 3: tạo reports/check_<mã dữ liệu>.csv (báo cáo kiểm tra dữ liệu) và tự đối chiếu số kỳ vọng."""
from __future__ import annotations

import pandas as pd

from src.utils import TABLES, ensure_dir, folder, get_logger, table_file

log = get_logger("check")

COLUMNS = [
    "ma_du_lieu", "moc", "ngay", "tai_ve_ok",
    "listings_bytes", "calendar_bytes", "reviews_bytes",
    "listings_dong", "calendar_dong", "reviews_dong",
    "entire_home", "private_room", "khong_co_review", "thieu_price",
    "so_cot_listings", "so_cot_nan_90",
]


def _download_status(cfg, snap):
    raw_ok = all(table_file(cfg, "raw", snap, t).exists() for t in TABLES)
    if raw_ok:
        return "co"
    path = folder(cfg, "reports") / "download_log.csv"
    if path.exists():
        d = pd.read_csv(path)
        bad = d[(d["snapshot"] == snap) & (~d["status"].isin(["downloaded", "exists"]))]
        if len(bad):
            return str(bad.iloc[0]["status"])
    return "khong"


def _row(cfg, i, snap, thr):
    sizes = {}
    for t in TABLES:
        p = table_file(cfg, "raw", snap, t)
        sizes[t] = p.stat().st_size if p.exists() else ""
    listings = pd.read_csv(table_file(cfg, "interim", snap, "listings"), low_memory=False)
    calendar = pd.read_csv(table_file(cfg, "interim", snap, "calendar"), usecols=["listing_id"])
    reviews = pd.read_csv(table_file(cfg, "interim", snap, "reviews"), usecols=["id", "mau_llm", "nhan_tay"])
    # analysis_area là cột nhóm tự thêm, không thuộc tệp gốc -> không tính vào số cột.
    listings_raw = listings.drop(columns=["analysis_area"], errors="ignore")
    room = listings_raw["room_type"].value_counts()
    price_missing = len(listings_raw) if "price" not in listings_raw else int(listings_raw["price"].isna().sum())
    nan_ratio = listings_raw.isna().mean()
    row = {
        "ma_du_lieu": cfg["group"]["code"], "moc": i, "ngay": snap, "tai_ve_ok": _download_status(cfg, snap),
        "listings_bytes": sizes["listings"], "calendar_bytes": sizes["calendar"], "reviews_bytes": sizes["reviews"],
        "listings_dong": len(listings_raw), "calendar_dong": len(calendar), "reviews_dong": len(reviews),
        "entire_home": int(room.get("Entire home/apt", 0)), "private_room": int(room.get("Private room", 0)),
        "khong_co_review": int((listings_raw["number_of_reviews"] == 0).sum()),
        "thieu_price": price_missing,
        "so_cot_listings": listings_raw.shape[1], "so_cot_nan_90": int((nan_ratio >= thr).sum()),
    }
    extra = {
        "mau_llm": int(reviews["mau_llm"].sum()), "nhan_tay": int(reviews["nhan_tay"].sum()),
        "area_counts": listings["analysis_area"].value_counts() if "analysis_area" in listings else pd.Series(dtype=int),
    }
    return row, extra


def _cmp(name, value, expected):
    if expected is None:
        return True, f"  [-- ] {name}: {value} (chưa có số kỳ vọng)"
    good = value == expected
    return good, f"  [{'OK ' if good else 'SAI'}] {name}: {value} (cần {expected})"


def run(cfg):
    exp = cfg.get("expected", {})
    thr = cfg["qa"]["nan_col_threshold"]
    rows, all_ok = [], True
    last = len(cfg["snapshots"]) - 1
    for i, snap in enumerate(cfg["snapshots"]):
        row, extra = _row(cfg, i + 1, snap, thr)
        rows.append(row)
        print(f"\n--- Kiểm tra mốc {snap} ---")
        zero = exp.get("zero_reviews", [None] * len(cfg["snapshots"]))[i]
        checks = [
            _cmp("số dòng listings", row["listings_dong"], exp.get("listings_rows")),
            _cmp("số dòng calendar", row["calendar_dong"], exp.get("calendar_rows")),
            _cmp("số dòng reviews", row["reviews_dong"], exp.get("reviews_rows")),
            _cmp("Entire home/apt", row["entire_home"], exp.get("entire_home")),
            _cmp("Private room", row["private_room"], exp.get("private_room")),
            _cmp("listing có number_of_reviews = 0", row["khong_co_review"], zero),
            _cmp("review Mẫu LLM", extra["mau_llm"], exp.get("mau_llm")),
            _cmp("review Nhãn tay", extra["nhan_tay"], exp.get("nhan_tay")),
        ]
        if i == last:
            checks.append(_cmp("listing thiếu price (mốc cuối)", row["thieu_price"], exp.get("missing_price_last")))
        lo, hi = exp.get("area_listings_range", [None, None])
        if lo is not None and len(extra["area_counts"]):
            good = bool(extra["area_counts"].between(lo, hi).all())
            checks.append((good, f"  [{'OK ' if good else 'SAI'}] listing mỗi vùng ({lo}-{hi}): "
                                 f"{extra['area_counts'].sort_index().to_dict()}"))
        for good, msg in checks:
            all_ok &= good
            print(msg)
    out = ensure_dir(cfg["paths"]["reports"]) / f"check_{cfg['group']['code']}.csv"
    pd.DataFrame(rows, columns=COLUMNS).to_csv(out, index=False)
    print("\nTẤT CẢ KHỚP" if all_ok else "\nCÓ CHỖ SAI/CHƯA XÁC NHẬN - xem các dòng [SAI] ở trên")
    log.info("Đã ghi %s", out)
