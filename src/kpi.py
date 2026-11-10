"""Bước 7: tính KPI sau QA -> data/processed/kpi_*.csv (+ kpi_definitions.csv).

Mỗi KPI: tên -> mục tiêu -> công thức -> đơn vị. Chỉ dùng giá ở mốc cuối; ghi rõ tiền tệ.
Cột: kpi_id, snapshot, area ('ALL' = toàn thành phố), value, unit, n.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils import ensure_dir, folder, get_logger, price_col, table_file

log = get_logger("kpi")


def definitions(cfg):
    cur = cfg["currency"]
    return pd.DataFrame([
        ("K1", "Giá trung vị theo khu vực", "Biết mặt bằng giá từng khu vực (mốc cuối)",
         f"median({price_col(cfg)}) theo neighbourhood_cleansed, bỏ listing price_missing/price_outlier", f"{cur}/đêm", "kpi_median_price_by_area.csv"),
        ("K2", "Tỉ lệ nhà nguyên căn", "Theo dõi mức độ 'nhà ở' bị chuyển thành lưu trú ngắn hạn",
         "số listing Entire home/apt / tổng listing, theo mốc và khu vực", "%", "kpi_entire_home_share.csv"),
        ("K3", "Tỉ lệ ngày không còn trống (đại lượng thay thế cho công suất)", "Ước lượng mức độ khai thác theo thời gian",
         "1 - mean(available) trong calendar, theo mốc và khu vực (không phân biệt đã đặt hay chủ chặn lịch)", "%", "kpi_unavailable_day_rate.csv"),
        ("K4", "Tỉ lệ listing của chủ nhà nhiều căn", "Theo dõi mức độ thương mại hoá",
         "số listing có calculated_host_listings_count > 1 / tổng listing", "%", "kpi_multi_listing_host_share.csv"),
        ("K5", "Tỉ lệ listing chưa có review", "Theo dõi listing mới/ít hoạt động",
         "số listing có number_of_reviews = 0 / tổng listing", "%", "kpi_zero_review_share.csv"),
        ("K6", "Số review 12 tháng gần nhất trung bình mỗi listing", "Đo mức độ sôi động theo thời gian",
         "mean(number_of_reviews_ltm)", "review/listing", "kpi_reviews_ltm.csv"),
        ("K7", "Tỉ lệ review tiêu cực (từ LLM)", "Chỉ ra khu vực khách phàn nàn nhiều",
         "số review sentiment=negative / số review được LLM gắn nhãn, theo khu vực", "%", "kpi_llm_negative_share_by_area.csv"),
    ], columns=["kpi_id", "ten", "muc_tieu", "cong_thuc", "don_vi", "tep_ket_qua"]).assign(
        ben_lien_quan=cfg["kpi"].get("stakeholder", ""))


def load_clean(cfg, snap):
    L = pd.read_csv(table_file(cfg, "processed", snap, "listings"), low_memory=False)
    L["qa_flags"] = L["qa_flags"].fillna("")
    C = pd.read_csv(table_file(cfg, "processed", snap, "calendar"), usecols=["listing_id", "available"])
    return L, C


def grouped(df, snap, area_col, value_fn, kid, unit, min_n):
    """Một dòng toàn thành phố ('ALL') + một dòng mỗi khu vực đủ cỡ mẫu."""
    rows = [{"kpi_id": kid, "snapshot": snap, "area": "ALL", "value": value_fn(df), "unit": unit, "n": len(df)}]
    if area_col in df.columns:
        for area, g in df.groupby(area_col):
            if len(g) >= min_n:
                rows.append({"kpi_id": kid, "snapshot": snap, "area": area, "value": value_fn(g), "unit": unit, "n": len(g)})
    return rows


def save(cfg, name, rows):
    out = ensure_dir(folder(cfg, "processed")) / name
    pd.DataFrame(rows).to_csv(out, index=False)
    log.info("-> %s (%d dòng)", out, len(rows))


def run(cfg):
    area_col, min_n = cfg["kpi"]["area_col"], cfg["kpi"]["min_area_listings"]
    pcol, cur = price_col(cfg), cfg["currency"]
    snaps = cfg["snapshots"]
    data = {s: load_clean(cfg, s) for s in snaps}
    ensure_dir(folder(cfg, "processed"))
    definitions(cfg).to_csv(folder(cfg, "processed") / "kpi_definitions.csv", index=False)

    # K1: chỉ mốc cuối, bỏ listing thiếu/ngoại lai giá
    last = snaps[-1]
    L = data[last][0]
    ok = L[~L["qa_flags"].str.contains("price_missing|price_outlier")]
    save(cfg, "kpi_median_price_by_area.csv",
         grouped(ok, last, area_col, lambda d: float(d[pcol].median()), "K1", f"{cur}/đêm", min_n))

    k2, k3, k4, k5, k6 = [], [], [], [], []
    for s in snaps:
        L, C = data[s]
        k2 += grouped(L, s, area_col, lambda d: float((d["room_type"] == "Entire home/apt").mean()), "K2", "ratio", min_n)
        area_of = L.set_index("id")[area_col] if area_col in L.columns else None
        Cj = C.copy()
        if area_of is not None:
            Cj[area_col] = Cj["listing_id"].map(area_of)
        Cj = Cj.dropna(subset=["available"])
        k3 += grouped(Cj, s, area_col, lambda d: float(1 - d["available"].mean()), "K3", "ratio", min_n * 365)
        if "calculated_host_listings_count" in L.columns:
            k4 += grouped(L, s, area_col, lambda d: float((d["calculated_host_listings_count"] > 1).mean()), "K4", "ratio", min_n)
        k5 += grouped(L, s, area_col, lambda d: float((d["number_of_reviews"] == 0).mean()), "K5", "ratio", min_n)
        if "number_of_reviews_ltm" in L.columns:
            k6 += grouped(L, s, area_col, lambda d: float(d["number_of_reviews_ltm"].mean()), "K6", "review/listing", min_n)
    save(cfg, "kpi_entire_home_share.csv", k2)
    save(cfg, "kpi_unavailable_day_rate.csv", k3)
    if k4:
        save(cfg, "kpi_multi_listing_host_share.csv", k4)
    save(cfg, "kpi_zero_review_share.csv", k5)
    if k6:
        save(cfg, "kpi_reviews_ltm.csv", k6)

    # K7: dùng kết quả LLM
    llm_path = folder(cfg, "processed") / "llm_results.csv"
    if llm_path.exists() and llm_path.stat().st_size > 0:
        res = pd.read_csv(llm_path, dtype={"review_id": "int64", "listing_id": "int64"}).dropna(subset=["sentiment"])
        L = data[last][0]
        res[area_col] = res["listing_id"].map(L.set_index("id")[area_col])
        k7 = grouped(res, last, area_col, lambda d: float((d["sentiment"] == "negative").mean()), "K7", "ratio",
                     cfg["kpi"]["min_area_reviews"])
        save(cfg, "kpi_llm_negative_share_by_area.csv", k7)
    else:
        log.warning("Chưa có llm_results.csv -> bỏ qua K7")
