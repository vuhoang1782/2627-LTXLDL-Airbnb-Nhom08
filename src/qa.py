"""QA: chọn cột dùng được, ép kiểu, gắn cờ bất thường, báo cáo tác động.

Đầu ra:
  reports/qa_report.csv                      mỗi quy tắc x mốc: điều kiện, lý do, hành động, số dòng, KPI trước/sau
  data/processed/listings_<mốc>.csv.gz       cột đã chọn + cờ qa_flag_*
  data/processed/calendar_<mốc>.csv.gz
  data/processed/reviews_unique.csv.gz       review đã gộp giữa các mốc (cột first_snapshot)
Nguyên tắc: gắn cờ trước, chỉ xóa dòng trùng; dòng bất thường chỉ bị loại khi tính KPI.
"""
import argparse
import json
from pathlib import Path

import pandas as pd
import yaml
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

DEFAULT_KEEP = {   # cột dùng được cho KPI / LLM (rút ra từ bảng % NaN); ghi đè được bằng qa.keep_cols
    "listings": [
        "id", "last_scraped", "host_id", "neighbourhood_cleansed", "neighbourhood_group_cleansed",
        "latitude", "longitude", "property_type", "room_type", "accommodates", "bathrooms",
        "bedrooms", "beds", "price", "minimum_nights", "maximum_nights", "availability_30",
        "availability_60", "availability_90", "availability_365", "number_of_reviews",
        "number_of_reviews_ltm", "estimated_occupancy_l365d", "first_review", "last_review",
        "review_scores_rating", "reviews_per_month", "license", "host_is_superhost",
        "calculated_host_listings_count", "calculated_host_listings_count_entire_homes",
        "calculated_host_listings_count_private_rooms", "calculated_host_listings_count_shared_rooms",
    ],
    "calendar": ["listing_id", "date", "available", "minimum_nights", "maximum_nights"],
    "reviews": ["listing_id", "id", "date", "comments"],
}
ID_COL = {"listings": "id", "calendar": "listing_id", "reviews": "listing_id"}
PRICE_COLS = ["price"]
BOOL_COLS = ["host_is_superhost", "available"]
DATE_COLS = ["last_scraped", "first_review", "last_review", "date"]
MISSING_COLS = ["price", "bedrooms", "beds", "bathrooms", "review_scores_rating"]
ROOM_TYPES = ["Entire home/apt", "Private room", "Hotel room", "Shared room"]
INT_COLS = ["id", "host_id", "listing_id", "accommodates", "bedrooms", "beds", "minimum_nights", "maximum_nights",
            "availability_30", "availability_60", "availability_90", "availability_365", "number_of_reviews",
            "number_of_reviews_ltm", "estimated_occupancy_l365d", "calculated_host_listings_count",
            "calculated_host_listings_count_entire_homes", "calculated_host_listings_count_private_rooms",
            "calculated_host_listings_count_shared_rooms"]
CRITICAL = {"dup_listing", "dup_calendar", "dup_review", "missing_price", "price_out_of_range", "min_nights_cap",
            "coord_out_of_city", "orphan_calendar"}      # còn lại: warning


class Report:
    COLS = ["snapshot", "rule_id", "muc_do", "bang", "nhom", "dieu_kien", "ly_do", "hanh_dong", "status",
            "so_dong", "tong_dong", "pct", "kpi", "kpi_truoc", "kpi_sau", "ghi_chu"]

    def __init__(self):
        self.rows = []

    def add(self, snap, rid, bang, nhom, cond, why, action, status="applied", n=None, total=None,
            kpi=None, before=None, after=None, note=""):
        pct = round(n / total * 100, 2) if n is not None and total else None
        level = "critical" if rid in CRITICAL else "warning"
        self.rows.append(dict(zip(self.COLS, [snap, rid, level, bang, nhom, cond, why, action, status,
                                              n, total, pct, kpi, before, after, note])))


def kpis(df):
    """KPI dùng để đo tác động của QA (đổi ở đây nếu chốt KPI khác)."""
    out = {}
    if "price" in df and df["price"].notna().any():
        out["gia_trung_vi_usd"] = round(float(df["price"].median()), 2)
    if "minimum_nights" in df and df["minimum_nights"].notna().any():
        out["pct_min_nights_ge_30"] = round(float((df["minimum_nights"].dropna() >= 30).mean() * 100), 2)
    return out


def rule(rep, snap, df, rid, bang, nhom, cond, why, action, needs, mask_fn, exclude=False):
    """Gắn cờ qa_flag_<rid>. exclude=True: đo KPI trước/sau khi loại các dòng bị cờ."""
    miss = [c for c in needs if c not in df.columns]
    if miss:
        rep.add(snap, rid, bang, nhom, cond, why, action, status="skipped", note="thiếu cột " + ", ".join(miss))
        return
    mask = mask_fn(df).fillna(False).astype(bool)
    note = ""
    n, total = int(mask.sum()), len(df)
    df["qa_flag_" + rid] = mask
    if total and n / total > 0.5 and not rid.startswith("missing_"):
        note = f"CẢNH BÁO: {n/total:.0%} dòng bị cờ, kiểm tra lại quy tắc"
        print(f"  [!] {snap} {rid}: {note}")
    if exclude and bang == "listings" and kpis(df):     # KPI chỉ có nghĩa ở bảng listings
        before, after = kpis(df), kpis(df[~mask])
        for k, v in before.items():
            rep.add(snap, rid, bang, nhom, cond, why, action, n=n, total=total, kpi=k, before=v,
                    after=after.get(k), note=note)
    else:
        rep.add(snap, rid, bang, nhom, cond, why, action, n=n, total=total, note=note)


def drop_dups(rep, snap, df, rid, bang, keys, why):
    keys = [k for k in keys if k in df.columns]
    cond = "trùng " + ", ".join(keys)
    if not keys:
        rep.add(snap, rid, bang, "trùng", cond, why, "giữ bản đầu", status="skipped", note="thiếu cột khóa")
        return df
    mask = df.duplicated(subset=keys)
    n, total = int(mask.sum()), len(df)
    if bang == "listings" and kpis(df):
        before, after = kpis(df), kpis(df[~mask])
        for k, v in before.items():
            rep.add(snap, rid, bang, "trùng", cond, why, "giữ bản đầu, xóa bản sau", n=n, total=total,
                    kpi=k, before=v, after=after.get(k))
    else:
        rep.add(snap, rid, bang, "trùng", cond, why, "giữ bản đầu, xóa bản sau", n=n, total=total)
    return df[~mask].copy()


def coerce_types(rep, snap, bang, df):
    for col in list(df.columns):
        s = df[col]
        if is_numeric_dtype(s) or is_bool_dtype(s) or is_datetime64_any_dtype(s):
            continue            # đã đúng kiểu (pandas mới dùng 'string', cũ dùng 'object')
        if col in PRICE_COLS:
            df[col] = pd.to_numeric(s.str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
            cond, action = f"{col} là chuỗi có '$' và dấu phẩy", "ép sang số thực"
        elif col in BOOL_COLS:
            df[col] = s.map({"t": True, "f": False})
            cond, action = f"{col} là chữ t/f", "ép sang True/False"
        elif col in DATE_COLS:
            df[col] = pd.to_datetime(s, errors="coerce")
            cond, action = f"{col} là chuỗi ngày", "ép sang datetime"
        else:
            continue
        n = int(s.notna().sum())
        failed = int((s.notna() & df[col].isna()).sum())
        rep.add(snap, f"type_{col}", bang, "kiểu sai", cond, "chuỗi không tính toán/so sánh được", action,
                n=n, total=len(df), note=f"không đọc được: {failed}")


def cast_ints(df):
    """Cột đếm: float/NaN -> Int64 (số nguyên, cho phép rỗng) nếu mọi giá trị đều nguyên."""
    for col in INT_COLS:
        if col in df.columns and is_numeric_dtype(df[col]) and not is_bool_dtype(df[col]):
            v = df[col].dropna()
            if (v == v.round()).all():
                df[col] = df[col].astype("Int64")


def read_table(path, id_col, ids, keep, chunksize=500_000):
    """Đọc .csv.gz, chỉ giữ cột `keep` (nếu có) và các dòng thuộc ids. Trả về (df, cột vắng)."""
    header = list(pd.read_csv(path, nrows=0).columns)
    cols = [c for c in keep if c in header]
    if id_col not in cols:
        cols.append(id_col)
    parts = []
    for ch in pd.read_csv(path, usecols=cols, chunksize=chunksize, low_memory=False):
        parts.append(ch[ch[id_col].isin(ids)] if ids is not None else ch)
    df = pd.concat(parts, ignore_index=True)
    return df[[c for c in keep if c in df.columns]], [c for c in keep if c not in header]


def load_ids(path, ma):
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    s = df.loc[df["Mã dữ liệu"].str.strip() == ma, "listing_id"].dropna().str.strip()
    if s.empty:
        raise ValueError(f"Không có listing nào cho '{ma}' trong {path}")
    return set(s.astype("int64"))


def geojson_names(path):
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    return {x["properties"].get("neighbourhood") for x in feats}


def run(cfg_path):
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    snaps = [str(s) for s in cfg["snapshots"]]
    q = cfg.get("qa", {})
    keep = {**DEFAULT_KEEP, **q.get("keep_cols", {})}
    price_max, nights_cap = q.get("price_max_usd", 10000), q.get("min_nights_cap", 365)
    bbox = q.get("bbox", {"lat": [40.4, 41.0], "lon": [-74.35, -73.6]})    # NYC; kiểm lại ở yaml
    dedupe_keys = q.get("dedupe_keys", ["id", "last_scraped"])
    ids = None
    if q.get("scope", "assigned") == "assigned":
        ids = load_ids(cfg["check"]["listing_file"], cfg["check"]["ma_du_lieu"])
    raw = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]
    out_dir, rep_dir = Path(cfg.get("processed_dir", "data/processed")), Path(cfg.get("reports_dir", "reports"))
    out_dir.mkdir(parents=True, exist_ok=True); rep_dir.mkdir(parents=True, exist_ok=True)
    rep = Report()
    L, C, R = {}, {}, {}

    for snap in snaps:
        print(f"QA mốc {snap} ...", flush=True)
        dfs = {}
        for name in ("listings", "calendar", "reviews"):
            df, absent = read_table(raw / snap / f"{name}.csv.gz", ID_COL[name], ids, keep[name])
            for c in absent:
                rep.add(snap, "col_missing", name, "thiếu", f"cột {c} không có trong tệp", "cột nằm trong danh sách dùng được",
                        "bỏ qua các quy tắc cần cột này", status="skipped", note=c)
            coerce_types(rep, snap, name, df)
            cast_ints(df)
            dfs[name] = df
        l, c, r = dfs["listings"], dfs["calendar"], dfs["reviews"]

        # ---- trùng trong mốc
        l = drop_dups(rep, snap, l, "dup_listing", "listings", dedupe_keys, "mỗi listing chỉ một bản ghi mỗi lần thu thập")
        c = drop_dups(rep, snap, c, "dup_calendar", "calendar", ["listing_id", "date"], "mỗi listing có một dòng mỗi ngày")
        r = drop_dups(rep, snap, r, "dup_review", "reviews", ["id"], "review id là duy nhất")

        # ---- thiếu
        for col in MISSING_COLS:
            rule(rep, snap, l, f"missing_{col}", "listings", "thiếu", f"{col} là NaN", "không tính được chỉ số dùng cột này",
                 "gắn cờ, không điền giá trị", [col], lambda d, col=col: d[col].isna())
        rule(rep, snap, l, "review_score_inconsistent", "listings", "thiếu", "number_of_reviews > 0 nhưng review_scores_rating NaN",
             "dữ liệu mâu thuẫn", "gắn cờ", ["number_of_reviews", "review_scores_rating"],
             lambda d: (d["number_of_reviews"] > 0) & d["review_scores_rating"].isna())
        rule(rep, snap, r, "review_comment_missing", "reviews", "thiếu", "comments là NaN", "không có văn bản để LLM đọc",
             "gắn cờ, không xóa", ["comments"], lambda d: d["comments"].isna())

        # ---- ngoại lai
        rule(rep, snap, l, "price_out_of_range", "listings", "ngoại lai", f"price <= 0 hoặc > {price_max}",
             "giá phi thực tế làm lệch trung vị/trung bình", "gắn cờ, loại khỏi KPI giá", ["price"],
             lambda d: (d["price"] <= 0) | (d["price"] > price_max), exclude=True)
        rule(rep, snap, l, "min_nights_cap", "listings", "ngoại lai", f"minimum_nights > {nights_cap}",
             "ngưỡng vô lý (hơn một năm)", "gắn cờ, loại khỏi KPI", ["minimum_nights"],
             lambda d: d["minimum_nights"] > nights_cap, exclude=True)
        rule(rep, snap, l, "coord_out_of_city", "listings", "ngoại lai", f"tọa độ ngoài hộp {bbox}",
             "listing nằm ngoài thành phố hoặc tọa độ sai", "gắn cờ, loại khỏi KPI", ["latitude", "longitude"],
             lambda d: ~(d["latitude"].between(*bbox["lat"]) & d["longitude"].between(*bbox["lon"])) & d["latitude"].notna(),
             exclude=True)

        rule(rep, snap, l, "price_suspicious_low", "listings", "ngoại lai", "0 < price < 10",
             "giá thấp bất thường (có thể nhập sai)", "gắn cờ", ["price"], lambda d: (d["price"] > 0) & (d["price"] < 10))
        rule(rep, snap, l, "inactive_listing", "listings", "ngoại lai", "availability_365 = 0 và number_of_reviews_ltm = 0",
             "listing không hoạt động làm lệch KPI thị trường", "gắn cờ, loại khỏi KPI",
             ["availability_365", "number_of_reviews_ltm"],
             lambda d: (d["availability_365"] == 0) & (d["number_of_reviews_ltm"] == 0), exclude=True)

        # ---- mâu thuẫn giữa các cột
        rule(rep, snap, l, "date_logic", "listings", "mâu thuẫn", "first_review > last_review", "thứ tự ngày vô lý",
             "gắn cờ", ["first_review", "last_review"], lambda d: d["first_review"] > d["last_review"])
        rule(rep, snap, l, "availability_logic", "listings", "mâu thuẫn",
             "availability_30 > 60, hoặc 60 > 90, hoặc 90 > 365", "ngày trống 30 ngày không thể lớn hơn 60 ngày",
             "gắn cờ", ["availability_30", "availability_60", "availability_90", "availability_365"],
             lambda d: (d["availability_30"] > d["availability_60"]) | (d["availability_60"] > d["availability_90"])
             | (d["availability_90"] > d["availability_365"]))
        rule(rep, snap, l, "host_count_mismatch", "listings", "mâu thuẫn",
             "calculated_host_listings_count != tổng entire_homes + private_rooms + shared_rooms",
             "tổng không khớp thì KPI % host nhiều listing không tin cậy", "gắn cờ",
             ["calculated_host_listings_count", "calculated_host_listings_count_entire_homes",
              "calculated_host_listings_count_private_rooms", "calculated_host_listings_count_shared_rooms"],
             lambda d: d["calculated_host_listings_count"] != d["calculated_host_listings_count_entire_homes"]
             + d["calculated_host_listings_count_private_rooms"] + d["calculated_host_listings_count_shared_rooms"])

        # ---- danh mục lệch
        rule(rep, snap, l, "room_type_unknown", "listings", "danh mục lệch", f"room_type không thuộc {ROOM_TYPES}",
             "nhãn lạ làm sai KPI theo loại phòng", "gắn cờ", ["room_type"],
             lambda d: d["room_type"].notna() & ~d["room_type"].isin(ROOM_TYPES))
        valid = geojson_names(raw / snap / "neighbourhoods.geojson")
        if valid is None:
            rep.add(snap, "neighbourhood_not_in_geojson", "listings", "danh mục lệch", "neighbourhood_cleansed không có trong geojson",
                    "không vẽ được bản đồ theo khu", "gắn cờ", status="skipped", note="thiếu neighbourhoods.geojson")
        else:
            rule(rep, snap, l, "neighbourhood_not_in_geojson", "listings", "danh mục lệch",
                 "neighbourhood_cleansed không có trong geojson", "không vẽ được bản đồ theo khu", "gắn cờ",
                 ["neighbourhood_cleansed"], lambda d: d["neighbourhood_cleansed"].notna() & ~d["neighbourhood_cleansed"].isin(valid))

        # ---- mồ côi (chỉ gắn cờ, không xóa)
        lid = set(l["id"]) if "id" in l else set()
        rule(rep, snap, c, "orphan_calendar", "calendar", "toàn vẹn", "listing_id không có trong listings cùng mốc",
             "không nối được bảng", "gắn cờ", ["listing_id"], lambda d: ~d["listing_id"].isin(lid))
        rule(rep, snap, r, "orphan_review", "reviews", "toàn vẹn", "listing_id không có trong listings cùng mốc",
             "không nối được bảng", "gắn cờ, không xóa (có thể thuộc mẫu LLM)", ["listing_id"], lambda d: ~d["listing_id"].isin(lid))
        L[snap], C[snap], R[snap] = l, c, r

    # ---- trùng giữa các mốc
    seen_l, seen_r, uniq = set(), set(), []
    for snap in snaps:
        l = L[snap]
        if {"id", "last_scraped"} <= set(l.columns):
            keys = pd.Series(list(zip(l["id"], l["last_scraped"])), index=l.index)
            rule(rep, snap, l, "stale_listing", "listings", "trùng giữa các mốc", "cùng (id, last_scraped) đã có ở mốc trước",
                 "bản ghi không được thu thập lại", "gắn cờ", ["id"], lambda d, k=keys, s=seen_l: k.isin(s))
            seen_l.update(keys)
        r = R[snap]
        rep_mask = r["id"].isin(seen_r)
        rep.add(snap, "review_repeat", "reviews", "trùng giữa các mốc", "review id đã có ở mốc trước",
                "review là dữ liệu tích lũy", "giữ một bản trong reviews_unique", n=int(rep_mask.sum()), total=len(r))
        uniq.append(r[~rep_mask].assign(first_snapshot=snap))
        seen_r.update(r["id"])

    # ---- xuất
    for snap in snaps:
        L[snap].to_csv(out_dir / f"listings_{snap}.csv.gz", index=False)
        C[snap].to_csv(out_dir / f"calendar_{snap}.csv.gz", index=False)
    pd.concat(uniq, ignore_index=True).to_csv(out_dir / "reviews_unique.csv.gz", index=False)
    pd.DataFrame(rep.rows, columns=Report.COLS).to_csv(rep_dir / "qa_report.csv", index=False)
    print(f"Đã ghi {rep_dir / 'qa_report.csv'} ({len(rep.rows)} dòng) và dữ liệu sạch vào {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    run(ap.parse_args().config)
