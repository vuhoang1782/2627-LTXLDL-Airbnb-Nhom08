"""Bước 4: làm sạch + bộ quy tắc QA.

Mỗi quy tắc ghi: tên -> điều kiện -> lý do -> hành động (ưu tiên GẮN CỜ ở cột qa_flags, chỉ xoá dòng trùng).
Ghi tác động (số dòng; KPI trước/sau) vào reports/qa_report.csv.
Dữ liệu sạch: data/processed/<mốc>/*.csv.gz.  Cột gần như trống: data/processed/unusable_columns.json.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.utils import TABLES, ensure_dir, folder, get_logger, price_col, table_file

log = get_logger("qa")


class QALog:
    def __init__(self):
        self.rows = []

    def add(self, snapshot, table, rule, condition, reason, action, rows_affected,
            kpi_name="", kpi_before=np.nan, kpi_after=np.nan):
        self.rows.append({
            "snapshot": snapshot, "table": table, "rule": rule, "condition": condition,
            "reason": reason, "action": action, "rows_affected": int(rows_affected),
            "kpi_name": kpi_name, "kpi_before": kpi_before, "kpi_after": kpi_after,
        })

    def save(self, path):
        pd.DataFrame(self.rows).to_csv(path, index=False)


# ---------- hàm chuyển kiểu ----------
def to_number(series):
    """'$1,250.00' -> 1250.0 ; không đọc được -> NaN."""
    if pd.api.types.is_numeric_dtype(series):
        return series.astype(float)
    cleaned = series.astype(str).str.replace(r"[^0-9.\-]", "", regex=True)
    return pd.to_numeric(cleaned.replace("", np.nan), errors="coerce").astype(float)


def to_flag01(series):
    """'t'/'f' (hoặc True/False) -> 1.0/0.0 ; khác -> NaN."""
    mapping = {"t": 1.0, "f": 0.0, "true": 1.0, "false": 0.0, "1": 1.0, "0": 0.0}
    return series.astype(str).str.strip().str.lower().map(mapping).astype(float)


def make_flags(index, masks):
    """Ghép các mặt nạ thành chuỗi cờ 'a|b|c' cho từng dòng."""
    if not masks:
        return pd.Series("", index=index)
    parts = pd.DataFrame({k: np.where(v.reindex(index).fillna(False), k, "") for k, v in masks.items()}, index=index)
    return parts.apply(lambda r: "|".join(x for x in r if x), axis=1)


def _median(s):
    s = s.dropna()
    return float(s.median()) if len(s) else np.nan


# ---------- làm sạch từng bảng ----------
def clean_calendar(C, snap, cfg, qlog):
    q = cfg["qa"]
    n0 = len(C)
    C = C.copy()
    C["date"] = pd.to_datetime(C["date"], errors="coerce")
    bad_date = C["date"].isna().sum()
    qlog.add(snap, "calendar", "C_TYPE_DATE", "date không đọc được thành ngày", "cần cột ngày đúng kiểu để nhóm theo thời gian",
             "chuyển sang datetime, lỗi -> NaT", bad_date)
    raw_av = C["available"].astype(str).str.strip().str.lower()
    C["available"] = to_flag01(C["available"])
    bad_av = (raw_av.isin(["nan", "none", ""]) | C["available"].notna()).eq(False).sum()
    qlog.add(snap, "calendar", "C_TYPE_AVAILABLE", "available không phải t/f", "tính tỉ lệ ngày trống cần giá trị 0/1",
             "chuyển t/f -> 1/0, giá trị lạ -> NaN", bad_av)
    if "price" in C.columns:
        C["price"] = to_number(C["price"])
    keys = q["dedupe_keys"]["calendar"]
    dup = C.duplicated(subset=keys, keep="first")
    qlog.add(snap, "calendar", "C_DUP_WITHIN", f"trùng khoá {keys} trong cùng mốc", "mỗi listing-ngày chỉ được có một dòng",
             "xoá bản trùng, giữ dòng đầu", dup.sum(), "n_calendar_rows", n0, n0 - int(dup.sum()))
    return C[~dup].copy()


def clean_reviews(R, snap, cfg, qlog):
    n0 = len(R)
    R = R.copy()
    raw = R["comments"].astype(object).where(R["comments"].notna(), "").astype(str)
    has_html = raw.str.contains(r"<br\s*/?>", regex=True)
    qlog.add(snap, "reviews", "R_HTML_TAGS", "comments chứa thẻ <br/>", "thẻ HTML làm nhiễu văn bản đưa vào LLM/baseline",
             "thay bằng khoảng trắng, lưu ở comment_clean", has_html.sum())
    R["comment_clean"] = (raw.str.replace(r"<br\s*/?>", " ", regex=True)
                             .str.replace(r"\s+", " ", regex=True).str.strip())
    R["date"] = pd.to_datetime(R["date"], errors="coerce")
    qlog.add(snap, "reviews", "R_TYPE_DATE", "date không đọc được thành ngày", "cần cột ngày đúng kiểu để nhóm theo thời gian",
             "chuyển sang datetime, lỗi -> NaT", R["date"].isna().sum())
    keys = cfg["qa"]["dedupe_keys"]["reviews"]
    dup = R.duplicated(subset=keys, keep="first")
    qlog.add(snap, "reviews", "R_DUP_WITHIN", f"trùng khoá {keys} trong cùng mốc", "một review chỉ được tính một lần",
             "xoá bản trùng, giữ dòng đầu", dup.sum(), "n_reviews", n0, n0 - int(dup.sum()))
    R = R[~dup].copy()
    empty = R["comment_clean"].eq("")
    R["qa_flags"] = np.where(empty, "empty_comment", "")
    R["llm_eligible"] = ~empty
    qlog.add(snap, "reviews", "R_EMPTY_COMMENT", "comment rỗng sau khi làm sạch", "không có văn bản thì LLM/baseline không có gì để phân tích",
             "gắn cờ empty_comment, loại khỏi mẫu LLM", empty.sum(), "n_reviews_llm_eligible", len(R), int((~empty).sum()))
    return R


def clean_listings(L, snap, cfg, qlog, cal_counts):
    q = cfg["qa"]
    pcol = price_col(cfg)
    L = L.copy()
    n0 = len(L)

    # 1) Cột gần như trống (>= ngưỡng NaN): lưu danh sách, không dùng cho KPI
    raw_cols = [c for c in L.columns if c != "analysis_area"]
    nan_ratio = L[raw_cols].isna().mean()
    empty_cols = nan_ratio[nan_ratio >= q["nan_col_threshold"]].index.tolist()
    qlog.add(snap, "listings", "L_HIGH_NAN_COLS", f"cột có >= {q['nan_col_threshold']:.0%} ô rỗng: {', '.join(empty_cols) or 'không có'}",
             "cột gần như trống không đủ dữ liệu để tính KPI", "gắn cờ cột (unusable_columns.json), không dùng cho KPI",
             len(empty_cols), "n_columns_usable", len(raw_cols), len(raw_cols) - len(empty_cols))

    # 2) Trùng trong cùng mốc
    keys = q["dedupe_keys"]["listings"]
    dup = L.duplicated(subset=keys, keep="first")
    qlog.add(snap, "listings", "L_DUP_WITHIN", f"trùng khoá {keys} trong cùng mốc", "mỗi listing chỉ được tính một lần",
             "xoá bản trùng, giữ dòng đầu", dup.sum(), "n_listings", n0, n0 - int(dup.sum()))
    L = L[~dup].copy()

    # 3) Kiểu sai: giá, phần trăm, t/f, ngày
    if "price" in L.columns:
        L[pcol] = to_number(L["price"])
        failed = (L["price"].notna() & L[pcol].isna()).sum()
    else:
        L[pcol], failed = np.nan, 0
    qlog.add(snap, "listings", "L_TYPE_PRICE", "price là chuỗi ('$1,250.00') hoặc không đọc được thành số",
             "cần số để tính KPI giá", f"bỏ ký hiệu tiền/dấu phẩy -> {pcol} ({cfg['currency']}); lỗi -> NaN", failed)
    for col in ("host_response_rate", "host_acceptance_rate"):
        if col in L.columns:
            L[col] = to_number(L[col]) / 100.0
    for col in ("instant_bookable", "host_is_superhost", "has_availability"):
        if col in L.columns:
            L[col] = to_flag01(L[col])
    bad_dates = 0
    for col in ("last_scraped", "host_since", "first_review", "last_review"):
        if col in L.columns:
            parsed = pd.to_datetime(L[col], errors="coerce")
            bad_dates += int((L[col].notna() & parsed.isna()).sum())
            L[col] = parsed
    qlog.add(snap, "listings", "L_TYPE_DATE", "cột ngày không đọc được", "cần datetime đúng kiểu",
             "chuyển sang datetime, lỗi -> NaT", bad_dates)

    masks = {}
    # 4) Thiếu giá + ngoại lai giá
    masks["price_missing"] = L[pcol].isna()
    valid_before = int((~masks["price_missing"]).sum())
    qlog.add(snap, "listings", "L_MISSING_PRICE", "price rỗng", "không thể tính KPI giá cho listing này",
             "gắn cờ price_missing, loại khỏi KPI giá", masks["price_missing"].sum(),
             "n_listings_with_price", len(L), valid_before)
    out_price = L[pcol].notna() & ((L[pcol] < q["price_min_usd"]) | (L[pcol] > q["price_max_usd"]))
    masks["price_outlier"] = out_price
    qlog.add(snap, "listings", "L_OUTLIER_PRICE", f"{pcol} < {q['price_min_usd']} hoặc > {q['price_max_usd']}",
             "giá cực đoan làm lệch trung bình; thường do nhập sai hoặc giá giữ chỗ", "gắn cờ price_outlier, loại khỏi KPI giá",
             out_price.sum(), f"median_{pcol}", _median(L[pcol]), _median(L.loc[~out_price, pcol]))

    # 5) Ngoại lai số đêm tối thiểu
    if "minimum_nights" in L.columns:
        mn = to_number(L["minimum_nights"])
        masks["min_nights_outlier"] = mn > q["min_nights_cap"]
        qlog.add(snap, "listings", "L_OUTLIER_MIN_NIGHTS", f"minimum_nights > {q['min_nights_cap']}", "giá trị vô lý (hơn 1 năm)",
                 "gắn cờ min_nights_outlier", masks["min_nights_outlier"].sum(), "mean_minimum_nights",
                 float(mn.mean()), float(mn[~masks["min_nights_outlier"]].mean()))

    # 6) Danh mục lệch: room_type
    room = L["room_type"].str.strip()
    L["room_type"] = room
    masks["unknown_room_type"] = ~room.isin(q["allowed_room_types"])
    qlog.add(snap, "listings", "L_CATEGORY_ROOM_TYPE", f"room_type ngoài {q['allowed_room_types']}", "nhãn lạ làm sai thống kê theo loại phòng",
             "gắn cờ unknown_room_type", masks["unknown_room_type"].sum(), "n_listings", len(L), len(L))
    shares = room.value_counts(normalize=True)
    if len(shares) and shares.iloc[0] >= q["imbalance_threshold"]:
        qlog.add(snap, "listings", "L_CATEGORY_IMBALANCE",
                 f"loại phòng '{shares.index[0]}' chiếm {shares.iloc[0]:.1%} (>= {q['imbalance_threshold']:.0%})",
                 "một nhóm áp đảo làm số trung bình chung phản ánh gần như chỉ nhóm đó",
                 "ghi chú: báo cáo KPI theo từng loại phòng, không chỉ gộp", int((room != shares.index[0]).sum()))

    # 7) Khu vực quá ít listing
    area_col = cfg["kpi"]["area_col"]
    if area_col in L.columns:
        L[area_col] = L[area_col].str.strip()
        cnt = L[area_col].map(L[area_col].value_counts())
        masks["sparse_neighbourhood"] = cnt < q["min_area_listings"]
        qlog.add(snap, "listings", "L_SPARSE_AREA", f"khu vực có < {q['min_area_listings']} listing", "mẫu quá nhỏ, KPI theo khu vực không ổn định",
                 "gắn cờ sparse_neighbourhood, không công bố KPI cho khu vực đó", masks["sparse_neighbourhood"].sum())

    # 8) Toạ độ
    b = q["bbox"]
    lat, lon = to_number(L["latitude"]), to_number(L["longitude"])
    masks["bad_coords"] = (lat.isna() | lon.isna() | (lat < b["lat_min"]) | (lat > b["lat_max"])
                           | (lon < b["lon_min"]) | (lon > b["lon_max"]))
    qlog.add(snap, "listings", "L_BAD_COORDS", "toạ độ rỗng hoặc ngoài khung thành phố", "listing sai vị trí làm sai bản đồ/KPI không gian",
             "gắn cờ bad_coords", masks["bad_coords"].sum())

    # 9) Ngày thu thập lệch so với mốc
    if "last_scraped" in L.columns:
        gap = (L["last_scraped"] - pd.Timestamp(snap)).abs().dt.days
        masks["scrape_date_mismatch"] = gap > q["scrape_date_tolerance_days"]
        qlog.add(snap, "listings", "L_SCRAPE_DATE", f"last_scraped lệch mốc > {q['scrape_date_tolerance_days']} ngày",
                 "dòng không thuộc đúng bản chụp", "gắn cờ scrape_date_mismatch", masks["scrape_date_mismatch"].sum())

    # 10) Lịch không đủ số ngày
    n_days = L["id"].map(cal_counts).fillna(0)
    masks["calendar_incomplete"] = n_days != q["calendar_days"]
    qlog.add(snap, "listings", "L_CALENDAR_COMPLETE", f"số ngày trong calendar != {q['calendar_days']}", "thiếu ngày làm sai tỉ lệ ngày trống",
             "gắn cờ calendar_incomplete", masks["calendar_incomplete"].sum())

    L["qa_flags"] = make_flags(L.index, masks)
    return L, empty_cols


def add_flag(L, mask, name):
    cur = L["qa_flags"].fillna("")
    L.loc[mask, "qa_flags"] = np.where(cur[mask] == "", name, cur[mask] + "|" + name)


def run(cfg):
    qlog, frames, unusable = QALog(), {}, {}
    for snap in cfg["snapshots"]:
        L = pd.read_csv(table_file(cfg, "interim", snap, "listings"), low_memory=False)
        C = pd.read_csv(table_file(cfg, "interim", snap, "calendar"), low_memory=False)
        R = pd.read_csv(table_file(cfg, "interim", snap, "reviews"), low_memory=False)
        C = clean_calendar(C, snap, cfg, qlog)
        R = clean_reviews(R, snap, cfg, qlog)
        L, empty_cols = clean_listings(L, snap, cfg, qlog, C.groupby("listing_id").size())
        frames[snap], unusable[snap] = (L, C, R), empty_cols

    # Trùng GIỮA các mốc: cùng (id, last_scraped) xuất hiện ở hơn một mốc => bản chụp bị chép lại
    if all("last_scraped" in frames[s][0].columns for s in cfg["snapshots"]):
        allkeys = pd.concat([frames[s][0][["id", "last_scraped"]].assign(snap=s) for s in cfg["snapshots"]])
        multi = allkeys.groupby(["id", "last_scraped"])["snap"].transform("nunique") > 1
        allkeys["stale"] = multi.to_numpy()
        for snap in cfg["snapshots"]:
            L = frames[snap][0]
            stale_ids = set(allkeys.loc[(allkeys["snap"] == snap) & allkeys["stale"], "id"])
            mask = L["id"].isin(stale_ids)
            add_flag(L, mask, "stale_across_snapshots")
            qlog.add(snap, "listings", "L_DUP_ACROSS", "cùng (id, last_scraped) xuất hiện ở nhiều mốc",
                     "bản chụp bị chép lại thì các mốc không độc lập", "gắn cờ stale_across_snapshots", mask.sum(),
                     "n_listings", len(L), len(L) - int(mask.sum()))

    for snap in cfg["snapshots"]:
        L, C, R = frames[snap]
        out = ensure_dir(folder(cfg, "processed", snap))
        L.to_csv(out / "listings.csv.gz", index=False)
        C.to_csv(out / "calendar.csv.gz", index=False)
        R.to_csv(out / "reviews.csv.gz", index=False)
    proc = ensure_dir(folder(cfg, "processed"))
    (proc / "unusable_columns.json").write_text(json.dumps(unusable, ensure_ascii=False, indent=2), encoding="utf-8")
    qpath = ensure_dir(folder(cfg, "reports")) / "qa_report.csv"
    qlog.save(qpath)
    log.info("QA xong: %d dòng quy tắc -> %s", len(qlog.rows), qpath)
