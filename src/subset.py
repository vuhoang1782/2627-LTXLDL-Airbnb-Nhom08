"""Bước 2: lọc dữ liệu thô theo danh sách ID của nhóm (listing / review).

Nếu không có tệp ID (ví dụ giảng viên chạy trên mốc khác), dùng lấy mẫu cố định theo seed.
Kết quả ghi vào data/interim/<mốc>/ (không commit).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.utils import ensure_dir, folder, get_logger, table_file

log = get_logger("subset")


def _is_x(series):
    return series.astype(str).str.strip().str.lower().eq("x")


def filter_in_chunks(path, id_col, keep_ids, usecols=None, chunksize=500_000):
    """Đọc tệp lớn theo khối, lọc ngay trong khối để không tràn RAM."""
    kept = []
    for chunk in pd.read_csv(path, chunksize=chunksize, usecols=usecols):
        kept.append(chunk[chunk[id_col].isin(keep_ids)])
    return pd.concat(kept, ignore_index=True)


def _ids_from_sheets(cfg):
    g, sc = cfg["group"], cfg["subset"]
    # ID dài tới 19 chữ số -> ép int64 để không bị làm tròn thành số thực.
    lst = pd.read_csv(sc["listing_ids"], dtype={"listing_id": "int64"})
    rev = pd.read_csv(sc["review_ids"], dtype={"review_id": "int64", "listing_id": "int64"})
    lst = lst[(lst["Lớp"] == g["class"]) & (lst["Nhóm"] == g["number"])].copy()
    rev = rev[(rev["Lớp"] == g["class"]) & (rev["Nhóm"] == g["number"])].copy()
    if lst.empty or rev.empty:
        raise SystemExit(f"Không thấy dòng của {g['class']} - nhóm {g['number']} trong tệp ID.")
    rev["mau_llm"] = _is_x(rev["Mẫu LLM"])
    rev["nhan_tay"] = _is_x(rev["Nhãn tay"])
    return lst[["listing_id", "analysis_area"]], rev[["review_id", "listing_id", "mau_llm", "nhan_tay"]]


def _ids_fallback(cfg):
    """Không có tệp ID: lấy mẫu ngẫu nhiên cố định (seed) để pipeline vẫn chạy được."""
    sc, seed = cfg["subset"], cfg.get("seed", 42)
    log.warning("Không thấy tệp ID của nhóm -> lấy mẫu ngẫu nhiên (seed=%s)", seed)
    first, last = cfg["snapshots"][0], cfg["snapshots"][-1]
    ids = pd.read_csv(table_file(cfg, "raw", first, "listings"), usecols=["id"])["id"].drop_duplicates()
    ids = ids.sample(min(len(ids), sc["fallback_listing_sample"]), random_state=seed)
    lst = pd.DataFrame({"listing_id": ids.sort_values().to_numpy(), "analysis_area": pd.NA})
    rev = filter_in_chunks(table_file(cfg, "raw", last, "reviews"), "listing_id", set(lst["listing_id"]),
                           usecols=["listing_id", "id"], chunksize=sc.get("chunksize", 500_000))
    rev = rev.rename(columns={"id": "review_id"}).drop_duplicates("review_id")
    rev = rev.sample(min(len(rev), sc["fallback_review_sample"]), random_state=seed).reset_index(drop=True)
    n_llm = min(len(rev), cfg["llm"]["sample_size"])
    llm_idx = rev.sample(n_llm, random_state=seed).index
    rev["mau_llm"] = rev.index.isin(llm_idx)
    hand_idx = rev[rev["mau_llm"]].head(cfg["llm"]["hand_label_size"]).index
    rev["nhan_tay"] = rev.index.isin(hand_idx)
    return lst, rev


def read_group_ids(cfg):
    sc = cfg["subset"]
    if Path(sc["listing_ids"]).exists() and Path(sc["review_ids"]).exists():
        return _ids_from_sheets(cfg)
    return _ids_fallback(cfg)


def process_snapshot(cfg, snap, lst, rev):
    sc = cfg["subset"]
    chunksize = sc.get("chunksize", 500_000)
    cal_cols = set(sc["calendar_columns"])
    out = ensure_dir(folder(cfg, "interim", snap))
    listing_ids = set(lst["listing_id"])

    listings = pd.read_csv(table_file(cfg, "raw", snap, "listings"), low_memory=False)
    listings = listings[listings["id"].isin(listing_ids)].copy()
    listings["analysis_area"] = listings["id"].map(lst.set_index("listing_id")["analysis_area"])

    # usecols dạng hàm: cột nào có thì lấy, thiếu (vd. price ở mốc mới) thì bỏ qua, không lỗi.
    calendar = filter_in_chunks(table_file(cfg, "raw", snap, "calendar"), "listing_id", listing_ids,
                                usecols=lambda c: c in cal_cols, chunksize=chunksize)

    reviews = filter_in_chunks(table_file(cfg, "raw", snap, "reviews"), "id", set(rev["review_id"]),
                               chunksize=chunksize)
    info = rev.set_index("review_id")
    for col in ("mau_llm", "nhan_tay"):
        reviews[col] = reviews["id"].map(info[col]).fillna(False).astype(bool)

    if len(listings) != len(listing_ids):
        log.warning("%s: chỉ tìm thấy %d/%d listing", snap, len(listings), len(listing_ids))
    log.info("%s: listings=%d calendar=%d reviews=%d", snap, len(listings), len(calendar), len(reviews))
    listings.to_csv(out / "listings.csv.gz", index=False)
    calendar.to_csv(out / "calendar.csv.gz", index=False)
    reviews.to_csv(out / "reviews.csv.gz", index=False)


def run(cfg):
    lst, rev = read_group_ids(cfg)
    log.info("ID của nhóm: %d listing, %d review", len(lst), len(rev))
    for snap in cfg["snapshots"]:
        process_snapshot(cfg, snap, lst, rev)
