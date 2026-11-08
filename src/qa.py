"""QA: chọn cột dùng được, ép kiểu, gắn cờ bất thường, báo cáo tác động.

Đầu ra:
  reports/qa_report.csv                        mỗi quy tắc x mốc: điều kiện, lý do, hành động, số dòng, KPI trước/sau
  data/processed/<mốc>/listings.parquet        cột đã chọn + cờ qa_flag_*
  data/processed/<mốc>/calendar.parquet
  data/processed/<mốc>/reviews.parquet         review của mốc đó (không có cột comments cho nhẹ)
  data/processed/<mốc>/rejected_<bảng>.csv     dòng trùng bị loại (chỉ có khi có dòng bị loại)
  data/processed/reviews_unique.parquet        review gộp giữa các mốc, có comments, cột first_snapshot
  data/processed/review_sample_llm.csv         mẫu LLM (1000) + mẫu nhãn tay (100), gộp, để llm.py đọc hết
  data/labels/hand_labels.csv                  100 review để tự gán nhãn tay (tạo một lần, KHÔNG bao giờ ghi đè)
Cột giữ lại được chọn theo 7 KPI của nhóm (giá theo quận x loại phòng, Wi-Fi + bếp, 3 đêm liên tiếp,
giá theo khu phố qua 4 mốc, Superhost, review tiêu cực, review phàn nàn theo khía cạnh).
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
        "id", "last_scraped", "neighbourhood_cleansed", "neighbourhood_group_cleansed", "latitude", "longitude",
        "room_type", "price", "minimum_nights", "maximum_nights", "availability_365", "number_of_reviews_ltm",
        "host_is_superhost", "amenities",      # amenities -> has_wifi, has_kitchen (rồi bỏ chuỗi gốc)
    ],
    "calendar": ["listing_id", "date", "available", "minimum_nights", "maximum_nights"],
    "reviews": ["listing_id", "id", "date", "comments"],
}
ID_COL = {"listings": "id", "calendar": "listing_id", "reviews": "listing_id"}
PRICE_COLS = ["price"]
BOOL_COLS = ["host_is_superhost", "available"]
DATE_COLS = ["last_scraped", "first_review", "last_review", "date"]
MISSING_COLS = ["price", "host_is_superhost"]
ROOM_TYPES = ["Entire home/apt", "Private room", "Hotel room", "Shared room"]
INT_COLS = ["id", "host_id", "listing_id", "accommodates", "bedrooms", "beds", "minimum_nights", "maximum_nights",
            "availability_30", "availability_60", "availability_90", "availability_365", "number_of_reviews",
            "number_of_reviews_ltm", "estimated_occupancy_l365d", "calculated_host_listings_count",
            "calculated_host_listings_count_entire_homes", "calculated_host_listings_count_private_rooms",
            "calculated_host_listings_count_shared_rooms"]
INFO = {"price_distribution", "amenities_variants", "analysis_area_summary"}   # không phải lỗi, chỉ để theo dõi
CRITICAL = {"dup_listing", "dup_calendar", "dup_review", "missing_price", "price_out_of_range", "min_nights_cap",
            "coord_out_of_city"}      # còn lại: warning


class Report:
    COLS = ["snapshot", "rule_id", "muc_do", "bang", "nhom", "dieu_kien", "ly_do", "hanh_dong", "status",
            "so_dong", "tong_dong", "pct", "kpi", "kpi_truoc", "kpi_sau", "ghi_chu"]

    def __init__(self):
        self.rows = []

    def add(self, snap, rid, bang, nhom, cond, why, action, status="applied", n=None, total=None,
            kpi=None, before=None, after=None, note=""):
        pct = round(n / total * 100, 2) if n is not None and total else None
        level = "critical" if rid in CRITICAL else "info" if rid in INFO else "warning"
        self.rows.append(dict(zip(self.COLS, [snap, rid, level, bang, nhom, cond, why, action, status,
                                              n, total, pct, kpi, before, after, note])))


def kpis(df):
    """KPI dùng để đo tác động của QA (đổi ở đây nếu chốt KPI khác)."""
    out = {}
    if "price" in df and df["price"].notna().any():
        out["gia_trung_vi_usd"] = round(float(df["price"].median()), 2)
    if "minimum_nights" in df and df["minimum_nights"].notna().any():     # gần với KPI "đáp ứng 3 đêm liên tiếp"
        out["pct_min_nights_le_3"] = round(float((df["minimum_nights"].dropna() <= 3).mean() * 100), 2)
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
        return df, df.iloc[0:0]
    mask = df.duplicated(subset=keys)
    n, total = int(mask.sum()), len(df)
    if bang == "listings" and kpis(df):
        before, after = kpis(df), kpis(df[~mask])
        for k, v in before.items():
            rep.add(snap, rid, bang, "trùng", cond, why, "giữ bản đầu, xóa bản sau", n=n, total=total,
                    kpi=k, before=v, after=after.get(k))
    else:
        rep.add(snap, rid, bang, "trùng", cond, why, "giữ bản đầu, xóa bản sau", n=n, total=total)
    return df[~mask].copy(), df[mask].assign(reject_reason=rid)


def coerce_types(rep, snap, bang, df):
    for col in list(df.columns):
        s = df[col]
        if is_numeric_dtype(s) or is_bool_dtype(s) or is_datetime64_any_dtype(s):
            continue            # đã đúng kiểu (pandas mới dùng 'string', cũ dùng 'object')
        if col in PRICE_COLS:
            df[col] = pd.to_numeric(s.str.replace(r"[^0-9.\-]", "", regex=True), errors="coerce")
            cond, action = f"{col} là chuỗi có '$' và dấu phẩy", "ép sang số thực"
        elif col in BOOL_COLS:
            df[col] = s.map({"t": True, "f": False}).astype("boolean")
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


def load_areas(path, ma):
    """{listing_id: analysis_area} từ file của giảng viên; None nếu file không có cột analysis_area."""
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    if "analysis_area" not in df.columns:
        return None
    df = df[df["Mã dữ liệu"].str.strip() == ma].dropna(subset=["listing_id"])
    return {int(k): v for k, v in zip(df["listing_id"].str.strip(), df["analysis_area"])}


def parse_amenities(x):
    """Chuỗi JSON '["Wifi", "Kitchen"]' -> list chữ thường; None nếu rỗng hoặc không đọc được."""
    if not isinstance(x, str):
        return None
    try:
        return [str(i).lower() for i in json.loads(x)]
    except ValueError:
        return None


def load_sample_ids(path, ma, col):
    """review_id được đánh dấu 'x' ở cột `col` (Mẫu LLM / Nhãn tay) của nhóm."""
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    df = df[(df["Mã dữ liệu"].str.strip() == ma) & (df[col].str.strip().str.lower() == "x")]
    return set(df["review_id"].dropna().str.strip().astype("int64"))


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
    areas = load_areas(cfg["check"]["listing_file"], cfg["check"]["ma_du_lieu"]) if ids is not None else None
    raw = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]
    out_dir, rep_dir = Path(cfg.get("processed_dir", "data/processed")), Path(cfg.get("reports_dir", "reports"))
    out_dir.mkdir(parents=True, exist_ok=True); rep_dir.mkdir(parents=True, exist_ok=True)
    rep = Report()
    L, C, R, REJ = {}, {}, {}, {}

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
        l, rj_l = drop_dups(rep, snap, l, "dup_listing", "listings", dedupe_keys, "mỗi listing chỉ một bản ghi mỗi lần thu thập")
        c, rj_c = drop_dups(rep, snap, c, "dup_calendar", "calendar", ["listing_id", "date"], "mỗi listing có một dòng mỗi ngày")
        r, rj_r = drop_dups(rep, snap, r, "dup_review", "reviews", ["id"], "review id là duy nhất")
        REJ[snap] = {"listings": rj_l, "calendar": rj_c, "reviews": rj_r}

        if areas is not None and "id" in l:
            l["analysis_area"] = l["id"].map(areas)

        # ---- tiện nghi: amenities -> has_wifi, has_kitchen (KPI Wi-Fi + bếp)
        if "amenities" in l.columns:
            lists = l["amenities"].map(parse_amenities)
            rule(rep, snap, l, "amenities_missing", "listings", "thiếu", "amenities rỗng hoặc không đọc được",
                 "không xác định được Wi-Fi và bếp", "gắn cờ, has_wifi và has_kitchen để trống", ["amenities"],
                 lambda d, x=lists: x.isna())
            l["has_wifi"] = lists.map(lambda x: pd.NA if x is None else any(("wifi" in i or "wi-fi" in i) and "pocket" not in i for i in x)).astype("boolean")
            l["has_kitchen"] = lists.map(lambda x: pd.NA if x is None else any("kitchen" in i and "kitchenette" not in i for i in x)).astype("boolean")
            top = lambda key: ", ".join(f"{k} ({v})" for k, v in pd.Series([i for x in lists.dropna() for i in x if key in i]).value_counts().head(5).items())
            rep.add(snap, "amenities_variants", "listings", "thông tin", "tên tiện nghi chứa wifi / kitchen",
                    "kiểm tra cách nhận diện Wi-Fi và bếp có đúng với dữ liệu thật", "chỉ báo cáo",
                    n=int((l["has_wifi"] & l["has_kitchen"]).sum()), total=len(l), note=f"wifi: {top('wi')} | kitchen: {top('kitchen')}")
            l = l.drop(columns=["amenities"])

        # ---- đối chiếu với danh sách của nhóm / calendar
        if ids is not None and "id" in l:
            miss_ids = ids - set(l["id"].dropna().astype("int64"))
            rep.add(snap, "expected_ids_missing", "listings", "toàn vẹn", "id có trong file của nhóm nhưng không có trong tệp mốc",
                    "mốc thiếu listing của nhóm, mẫu không cân bằng giữa các mốc", "báo cáo, không sửa",
                    n=len(miss_ids), total=len(ids), note="ví dụ: " + ",".join(map(str, sorted(miss_ids)[:5])))
        if {"listing_id", "date"} <= set(c.columns) and len(c):
            g = c.groupby("listing_id")["date"]
            bad = int(((g.nunique() != 365) | ((g.max() - g.min()).dt.days != 364)).sum())
            rep.add(snap, "calendar_not_365_days", "calendar", "toàn vẹn", "listing không đủ 365 ngày liên tục",
                    "calendar thiếu ngày làm sai KPI theo ngày", "báo cáo, không sửa", n=bad, total=int(c["listing_id"].nunique()))
        if "id" in l and "listing_id" in c:
            no_cal = set(l["id"].dropna().astype("int64")) - set(c["listing_id"].dropna().astype("int64"))
            rep.add(snap, "listing_without_calendar", "listings", "toàn vẹn", "listing không có dòng calendar nào",
                    "KPI 3 đêm liên tiếp sẽ là Unknown cho các listing này", "báo cáo, không sửa", n=len(no_cal), total=len(l))
        if "price" in l and l["price"].notna().any():
            p = l["price"].dropna()
            rep.add(snap, "price_distribution", "listings", "thông tin", "phân phối price sau khi ép kiểu",
                    "chọn ngưỡng price_max_usd bám theo dữ liệu", "chỉ báo cáo", n=len(p), total=len(l),
                    note=f"min={p.min():.0f}, median={p.median():.0f}, p99={p.quantile(0.99):.0f}, max={p.max():.0f}")

        # ---- thiếu
        for col in MISSING_COLS:
            rule(rep, snap, l, f"missing_{col}", "listings", "thiếu", f"{col} là NaN", "không tính được chỉ số dùng cột này",
                 "gắn cờ, không điền giá trị", [col], lambda d, col=col: d[col].isna())
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

        rule(rep, snap, l, "inactive_listing", "listings", "ngoại lai", "availability_365 = 0 và number_of_reviews_ltm = 0",
             "listing không hoạt động làm lệch KPI thị trường", "gắn cờ, loại khỏi KPI",
             ["availability_365", "number_of_reviews_ltm"],
             lambda d: (d["availability_365"] == 0) & (d["number_of_reviews_ltm"] == 0), exclude=True)

        # ---- danh mục lệch
        rule(rep, snap, l, "room_type_unknown", "listings", "danh mục lệch", f"room_type không thuộc {ROOM_TYPES}",
             "nhãn lạ làm sai KPI theo loại phòng", "gắn cờ", ["room_type"],
             lambda d: d["room_type"].notna() & ~d["room_type"].isin(ROOM_TYPES))
        valid = geojson_names(raw / snap / "neighbourhoods.geojson")
        if valid is None:
            rep.add(snap, "neighbourhood_not_in_geojson", "listings", "danh mục lệch", "neighbourhood_cleansed không có trong geojson",
                    "không vẽ được bản đồ theo khu", "gắn cờ", status="skipped",
                    note=f"không thấy {raw / snap / 'neighbourhoods.geojson'}")
        else:
            rule(rep, snap, l, "neighbourhood_not_in_geojson", "listings", "danh mục lệch",
                 "neighbourhood_cleansed không có trong geojson", "không vẽ được bản đồ theo khu", "gắn cờ",
                 ["neighbourhood_cleansed"], lambda d: d["neighbourhood_cleansed"].notna() & ~d["neighbourhood_cleansed"].isin(valid))

        L[snap], C[snap], R[snap] = l, c, r

    # ---- trùng giữa các mốc
    seen_r, uniq = set(), []
    for snap in snaps:
        r = R[snap]
        rep.add(snap, "review_dropped", "reviews", "trùng giữa các mốc", "review đã có ở mốc trước nhưng không còn ở mốc này",
                "review bị xóa hoặc ẩn sau khi thu thập", "giữ trong reviews_unique", n=len(seen_r - set(r["id"])), total=len(seen_r))
        rep_mask = r["id"].isin(seen_r)
        rep.add(snap, "review_repeat", "reviews", "trùng giữa các mốc", "review id đã có ở mốc trước",
                "review là dữ liệu tích lũy", "giữ một bản trong reviews_unique", n=int(rep_mask.sum()), total=len(r))
        uniq.append(r[~rep_mask].assign(first_snapshot=snap))
        seen_r.update(r["id"])

    # ---- cột khu vực: giúp chọn analysis_area / neighbourhood_group_cleansed / neighbourhood_cleansed cho KPI theo khu
    l0 = L[snaps[0]]
    for col in ("analysis_area", "neighbourhood_group_cleansed", "neighbourhood_cleansed"):
        if col in l0.columns:
            vc = l0[col].value_counts()
            rep.add("all", "analysis_area_summary", "listings", "thông tin", f"số listing mỗi giá trị của {col} (mốc đầu)",
                    "chọn cột khu vực đủ dữ liệu cho KPI theo khu", "chỉ báo cáo", n=int(vc.min()) if len(vc) else 0,
                    total=len(l0), note=f"{col}: {len(vc)} giá trị; nhỏ nhất={int(vc.min()) if len(vc) else 0}, "
                    f"lớn nhất={int(vc.max()) if len(vc) else 0}, mỗi giá trị < 10 listing: {int((vc < 10).sum())}")

    # ---- xuất
    ru = pd.concat(uniq, ignore_index=True)
    rf = cfg.get("check", {}).get("review_file")
    if rf and Path(rf).exists():
        sample = {}
        for name, col in (("llm_sample", "Mẫu LLM"), ("hand_label", "Nhãn tay")):
            sid = load_sample_ids(rf, cfg["check"]["ma_du_lieu"], col)
            sample[name] = sid
            miss = sid - set(ru["id"].dropna().astype("int64"))
            rep.add("all", f"{name}_missing_in_reviews", "reviews", "toàn vẹn", f"review_id thuộc cột '{col}' không có trong reviews_unique",
                    "không có văn bản để LLM hoặc so nhãn", "báo cáo", n=len(miss), total=len(sid),
                    note="ví dụ: " + ",".join(map(str, sorted(miss)[:5])))
        llm_ids, hand_ids = sample["llm_sample"], sample["hand_label"]
        rep.add("all", "hand_label_in_llm_sample", "reviews", "thông tin", "review nhãn tay cũng nằm trong mẫu LLM",
                "nếu không nằm trong thì LLM vẫn đọc cả hai tập", "chỉ báo cáo", n=len(hand_ids & llm_ids), total=len(hand_ids))
        sel = ru[ru["id"].isin(llm_ids | hand_ids)].rename(columns={"id": "review_id"}).sort_values("review_id")
        sel = sel.reset_index(drop=True)
        sel.insert(0, "stt", range(1, len(sel) + 1))
        sel["mau_llm"] = sel["review_id"].isin(llm_ids)
        sel["nhan_tay"] = sel["review_id"].isin(hand_ids)
        sel[["stt", "review_id", "listing_id", "date", "comments", "mau_llm", "nhan_tay", "qa_flag_review_comment_missing"]] \
            .to_csv(out_dir / "review_sample_llm.csv", index=False, encoding="utf-8-sig")
        hand = sel[sel["nhan_tay"]][["review_id", "listing_id", "date", "comments"]].reset_index(drop=True)
        hand.insert(0, "stt", range(1, len(hand) + 1))
        lab = Path(cfg.get("labels_dir", "data/labels")) / "hand_labels.csv"
        lab.parent.mkdir(parents=True, exist_ok=True)
        if lab.exists():
            print(f"  [i] {lab} đã tồn tại, không ghi đè (giữ nhãn bạn đã gán)")
        else:
            hand.to_csv(lab, index=False, encoding="utf-8-sig")
            print(f"  Đã tạo {lab} ({len(hand)} review) để gán nhãn tay")
    for snap in snaps:
        d = out_dir / snap
        d.mkdir(parents=True, exist_ok=True)
        L[snap].to_parquet(d / "listings.parquet", index=False)
        C[snap].to_parquet(d / "calendar.parquet", index=False)
        R[snap].drop(columns=["comments"], errors="ignore").to_parquet(d / "reviews.parquet", index=False)
        for name, rj in REJ[snap].items():
            if len(rj):
                rj.to_csv(d / f"rejected_{name}.csv", index=False)
    ru.to_parquet(out_dir / "reviews_unique.parquet", index=False)
    pd.DataFrame(rep.rows, columns=Report.COLS).to_csv(rep_dir / "qa_report.csv", index=False)
    print(f"Đã ghi {rep_dir / 'qa_report.csv'} ({len(rep.rows)} dòng) và dữ liệu sạch vào {out_dir}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    run(ap.parse_args().config)
