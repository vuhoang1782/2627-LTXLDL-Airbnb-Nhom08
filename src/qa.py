"""QA: lọc theo ID của nhóm, chuẩn hoá dữ liệu và tạo cờ hợp lệ. KHÔNG tính KPI (việc đó của kpi.py).

Nguyên tắc (theo QA_SPEC_10_RULES.md):
- Không sửa data/raw; chỉ đọc các cột cần dùng (LIST_COLS, CAL_COLS, REVIEW_COLS), đọc theo khối và lọc ngay theo ID của nhóm.
- Dòng không dùng được (khoá sai, trùng, xung đột, mồ côi) KHÔNG nằm trong bảng sạch mà ghi vào <bảng>_rejected.csv.gz.
- Không dropna toàn bảng, không tự điền dữ liệu thiếu. Thiếu / sai miền được phân biệt khi cần: cột True/False/NA.
- Tác động của QA lên giá trị trung vị / tỉ lệ (kpi, kpi_before, kpi_after) ghi ngay trong qa_report.csv khi làm sạch.

Hai lần chạy:  main(cfg)  (trước LLM: QA01-QA09)   và   main(cfg, post=True)  (sau LLM: QA10).
Chạy:  python -m src.qa --config X.yaml [--post]
Tệp phân công (config: assignments) là CSV: listing_ids cần cột listing_id (hoặc id); review_ids cần cột review_id,
nên có thêm listing_id, «Mẫu LLM», «Nhãn tay» (ô có chữ x = thuộc mẫu). Nếu tệp là của cả lớp (có cột «Lớp», «Nhóm»)
thì chỉ giữ dòng của nhóm khai trong config (group). Không có mục assignments thì lấy mẫu ngẫu nhiên cố định theo seed.
Đầu ra: data/processed/<mốc>/{listings,calendar,reviews}_clean.csv.gz, *_rejected.csv.gz, llm_clean.csv.gz, reports/qa_report.csv
"""
from __future__ import annotations

import json
import re
import sys

import numpy as np
import pandas as pd

from src.utils import (PROC, REPORTS, cli, clean_file, ensure_dir, get_logger, pct1, raw_file, read_clean,
                       read_text, snapshot_of, tables_snapshots, text_hash)

log = get_logger("qa")

# mã -> (tên, điều kiện, lý do, hành động)
RULES = {
    "QA01": ("Cột bắt buộc", "thiếu cột mà KPI cần", "không có dữ liệu nguồn thì không tính được KPI",
             "dừng ngay, báo cột thiếu và KPI bị chặn"),
    "QA02": ("Khoá và bản ghi trùng", "khoá thiếu/sai, trùng hoàn toàn, hoặc cùng khoá nhưng nội dung khác",
             "tránh tính lặp, đếm sai, nối nhầm",
             "ghi vào <bảng>_rejected.csv.gz: trùng hoàn toàn giữ 1 bản; khoá xung đột loại mọi dòng của khoá (không giữ bản đầu/cuối)"),
    "QA03": ("Ghép bảng đúng mốc", "listing_id của calendar/reviews không ghép được với listings cùng mốc",
             "không được lấy nhầm thông tin listing/loại phòng", "dòng mồ côi (orphan) ghi vào <bảng>_rejected.csv.gz"),
    "QA04": ("Giá", "giá thiếu, sai định dạng, không dương; hoặc giá dương nhưng ngoại lai (IQR)",
             "KPI giá cần giá dương hợp lệ, nhưng không tự loại giá cao có thật",
             "price_num chỉ giữ giá hợp lệ; giá ngoại lai chỉ gắn price_iqr_flag, vẫn tính"),
    "QA05": ("Amenities", "amenities thiếu hoặc không đọc được thành danh sách",
             "không xác định được Wi-Fi/Kitchen", "has_wifi/has_kitchen = True/False; thiếu hoặc lỗi = NA (không coi là False)"),
    "QA06": ("Nhãn nhóm", "room_type ngoài danh sách cho phép, hoặc thiếu quận/khu phố",
             "không nhóm đúng đối tượng", "gắn *_ok; chỉ loại khỏi KPI cần nhãn đó; không xoá dòng"),
    "QA07": ("Superhost", "host_is_superhost không phải t/f hoặc thiếu", "không xác định có phải Superhost",
             "is_superhost = True/False/NA; KPI 5 chỉ dùng True và False"),
    "QA08": ("Calendar và ràng buộc 3 đêm", "ngày sai; available không phải t/f; min/max không hợp lệ; thiếu ngày trong cửa sổ",
             "không đoán khả năng đặt phòng từ dữ liệu sai/thiếu",
             "available_state, constraints_state (T/F/U); giữ cả ngày U; không thêm ngày thiếu; không xét chuỗi 3 đêm ở đây"),
    "QA09": ("Nguồn review", "không đúng 1.000 review LLM + 100 nhãn tay, review rỗng, sai cặp review-listing, không ghép được loại phòng",
             "phải giữ đúng mẫu cố định", "llm_source_eligible; không tự chọn review thay thế"),
    "QA10": ("Kết quả LLM", "prediction thiếu/xung đột/sai ID-mốc-nội dung",
             "không tính KPI từ kết quả không đáng tin (giá trị sentiment/aspect đã bị lược đồ của llm.py ép đúng miền)",
             "prediction_ok, kpi6_eligible"),
}
REPORT_COLUMNS = ["snapshot", "rule", "name", "condition", "reason", "action", "n_affected", "n_valid",
                  "status", "note", "kpi", "kpi_before", "kpi_after"]

# cột bắt buộc -> KPI dùng cột đó
REQUIRED = {
    "listings": {"id": "1-7", "price": "1,4", "amenities": "2", "host_is_superhost": "5", "room_type": "1,2,3,6,7",
                 "neighbourhood_group_cleansed": "1-5", "neighbourhood_cleansed": "4"},
    "calendar": {"listing_id": "3", "date": "3", "available": "3", "minimum_nights": "3", "maximum_nights": "3"},
    "reviews": {"id": "6,7", "listing_id": "6,7", "comments": "6,7"},
}
# chỉ đọc đúng các cột cần dùng (cột thiếu thì bỏ qua ở đây, check_required báo)
LIST_COLS = list(REQUIRED["listings"])
CAL_COLS = list(REQUIRED["calendar"])
REVIEW_COLS = list(REQUIRED["reviews"])
WIFI = re.compile(r"^(fast )?wi-?fi( [-–] \d+(\.\d+)? ?mbps)?$")   # wifi, fast wifi - 75 mbps; KHÔNG khớp pocket wifi, ...over wifi...


class Report:
    def __init__(self):
        self.rows, self.rejected = [], {}

    def add(self, snap, rule, n_affected, n_valid, status=None, note="", kpi="", before=np.nan, after=np.nan):
        """kpi/before/after: tác động của quy tắc lên một giá trị trung vị hoặc tỉ lệ toàn mẫu (nếu có)."""
        name, cond, reason, action = RULES[rule]
        if status is None:
            status = "pass" if n_affected == 0 else "warning"
        self.rows.append({"snapshot": snap, "rule": rule, "name": name, "condition": cond, "reason": reason,
                          "action": action, "n_affected": int(n_affected), "n_valid": int(n_valid),
                          "status": status, "note": note, "kpi": kpi, "kpi_before": before, "kpi_after": after})

    def reject(self, table, df):
        self.rejected.setdefault(table, []).append(df)

    def flush(self, out):
        """Ghi các dòng bị loại của một mốc rồi xoá bộ nhớ đệm."""
        for table, parts in self.rejected.items():
            pd.concat(parts).to_csv(out / f"{table}_rejected.csv.gz", index=False)
        self.rejected = {}


def text(df, col):
    """Cột dạng chuỗi đã bỏ khoảng trắng; thiếu -> chuỗi rỗng."""
    return df[col].fillna("").astype(str).str.strip()


def clean_text(s, max_chars):
    """Bỏ <br>, gộp khoảng trắng, cắt độ dài: MỘT lần ở đây, nên LLM và baseline thấy cùng một văn bản."""
    s = s.fillna("").astype(str).str.strip().str.replace(r"<br\s*/?>", " ", regex=True)
    return s.str.replace(r"\s+", " ", regex=True).str.strip().str[:max_chars]


# ---------------------------------------------------------------- đầu vào: lọc theo ID của nhóm
def filter_table(path, key, keep, cols, chunksize=500_000):
    """Đọc theo khối, mọi cột là chuỗi nguyên văn, chỉ giữ cột trong cols và dòng có key thuộc keep."""
    if key not in pd.read_csv(path, nrows=0).columns:
        sys.exit(f"{path}: thiếu cột khoá '{key}'")
    chunks = pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=chunksize, usecols=lambda c: c in cols)
    return pd.concat([c[c[key].isin(keep)] for c in chunks], ignore_index=True)


def read_assignments(cfg):
    """Trả về (tập listing_id, bảng review: review_id, assigned_listing_id, mau_llm, nhan_tay)."""
    a = cfg.get("assignments")
    if not a:
        return sample_assignments(cfg)
    load = lambda k: pd.read_csv(cfg["_dir"] / a[k], dtype=str, keep_default_na=False, encoding="utf-8-sig") \
        .rename(columns=str.strip).apply(lambda s: s.str.strip())
    lst, rev = load("listing_ids"), load("review_ids")
    g = cfg.get("group")
    if g and "Lớp" in lst and "Lớp" in rev:                          # tệp của cả lớp: chỉ giữ dòng của nhóm
        mine = lambda d: d[(d["Lớp"] == g["class"]) & (d["Nhóm"] == str(g["number"]))]
        lst, rev = mine(lst), mine(rev)
    if "listing_id" not in lst and "id" in lst:                      # chấp nhận tên cột 'id'
        lst = lst.rename(columns={"id": "listing_id"})
    for df, col, name in ((lst, "listing_id", "listing_ids"), (rev, "review_id", "review_ids")):
        if col not in df or df[col].eq("").any() or df[col].duplicated().any():
            sys.exit(f"{a[name]}: thiếu cột '{col}', có ô rỗng hoặc ID trùng")
    llm_col, hand_col = a.get("llm_flag_column", "Mẫu LLM"), a.get("hand_flag_column", "Nhãn tay")
    if llm_col not in rev or hand_col not in rev:
        log.warning("review_ids thiếu cột '%s' hoặc '%s' -> không có manifest mẫu LLM, QA09 sẽ chặn KPI 6/7", llm_col, hand_col)
    flag = lambda c: rev[c].str.lower().eq("x") if c in rev else pd.Series(False, index=rev.index)
    manifest = pd.DataFrame({"review_id": rev["review_id"], "assigned_listing_id": rev["listing_id"] if "listing_id" in rev else "",
                             "mau_llm": flag(llm_col), "nhan_tay": flag(hand_col)})
    return set(lst["listing_id"]), manifest


def sample_assignments(cfg):
    """Không có tệp phân công: lấy mẫu cố định theo seed để quy trình vẫn chạy được."""
    seed, size, llm = cfg.get("seed", 42), cfg.get("fallback_sample", {}), cfg["llm"]
    log.warning("Config không có 'assignments' -> lấy mẫu ngẫu nhiên (seed=%s)", seed)
    first, last = cfg["snapshots"][0], snapshot_of(cfg, "llm_snapshot_index")
    ids = pd.read_csv(raw_file(first, "listings"), dtype=str, keep_default_na=False, usecols=["id"])["id"].drop_duplicates()
    lids = set(ids.sample(min(len(ids), size.get("listings", 1000)), random_state=seed))
    rev = filter_table(raw_file(last, "reviews"), "listing_id", lids, ["listing_id", "id"]).drop_duplicates("id")
    rev = rev.sample(min(len(rev), size.get("reviews", 5000)), random_state=seed).reset_index(drop=True)
    manifest = pd.DataFrame({"review_id": rev["id"], "assigned_listing_id": rev["listing_id"],
                             "mau_llm": rev.index < llm["sample_size"], "nhan_tay": rev.index < llm["hand_label_size"]})
    return lids, manifest


# ---------------------------------------------------------------- QA02, QA03: dòng không dùng được -> rejected
def split_keys(df, keys):
    """QA02: (dòng dùng được, dòng bị loại kèm reject_reason). Trùng hoàn toàn: giữ bản đầu; cùng khoá khác nội dung: loại mọi dòng của khoá."""
    valid = pd.concat([text(df, k).ne("") for k in keys], axis=1).all(axis=1)
    dup = df.duplicated(keep="first")                                              # bản sao trùng HOÀN TOÀN (cả nội dung)
    first = df[~dup & valid]
    clash = first[first.duplicated(subset=keys, keep=False)][keys].drop_duplicates()   # cùng khoá, khác nội dung
    conflict = df[keys].merge(clash.assign(_c=True), on=keys, how="left")["_c"].eq(True).to_numpy()
    reason = np.select([~valid.to_numpy(), dup.to_numpy(), conflict], ["key_invalid", "dup_exact", "key_conflict"], "")
    ok = reason == ""
    return df[ok].copy(), df[~ok].assign(reject_reason=reason[~ok])


def drop_orphans(df, L):
    """QA03: giữ dòng con ghép được với listings cùng mốc; dòng mồ côi đi vào rejected."""
    matched = text(df, "listing_id").isin(set(text(L, "id"))).to_numpy()
    return df[matched].copy(), df[~matched].assign(reject_reason="orphan")


def reasons(rej):
    c = rej["reject_reason"].value_counts()
    return " ".join(f"{k}={v}" for k, v in c.items()) or "không có"


def parse_price(s):
    """'$1,250.00' -> 1250.0. Trả về (số hoặc NaN, trạng thái ok/missing/parse_error/domain_error)."""
    txt = s.fillna("").astype(str).str.replace(r"[$,\s]", "", regex=True)
    num = pd.to_numeric(txt.replace("", np.nan), errors="coerce").astype(float)
    status = np.select([txt.eq(""), num.isna(), (num <= 0) | ~np.isfinite(num)],
                       ["missing", "parse_error", "domain_error"], default="ok")
    return num, pd.Series(status, index=s.index)


def parse_amenities(s):
    """Danh sách tiện nghi JSON -> (has_wifi, has_kitchen) kiểu boolean; thiếu hoặc không đọc được = NA."""
    wifi, kitchen = [], []
    for x in s.fillna("").astype(str):
        try:
            items = json.loads(x) if x.strip() else None
        except ValueError:
            items = None
        if isinstance(items, list) and all(isinstance(i, str) for i in items):
            names = [i.strip().lower() for i in items]
            wifi.append(any(WIFI.match(n) for n in names))
            kitchen.append("kitchen" in names)                      # khớp nguyên tên, không tìm chuỗi con
        else:
            wifi.append(pd.NA)
            kitchen.append(pd.NA)
    return pd.Series(wifi, index=s.index, dtype="boolean"), pd.Series(kitchen, index=s.index, dtype="boolean")


# ---------------------------------------------------------------- từng bảng
def qa_listings(L, snap, cfg, rep):
    q = cfg["qa"]
    L, rej = split_keys(L, ["id"])
    rep.reject("listings", rej)
    rep.add(snap, "QA02", len(rej), len(L), note=f"listings: {reasons(rej)}")

    # QA04 giá
    L["price_parsed"], L["price_status"] = parse_price(L["price"])
    L["price_num"] = L["price_parsed"].where(L["price_status"].eq("ok"))
    q1, q3 = L["price_num"].quantile([0.25, 0.75])
    L["price_iqr_flag"] = (L["price_num"] < q1 - 1.5 * (q3 - q1)) | (L["price_num"] > q3 + 1.5 * (q3 - q1))
    price_ok = L["price_status"].eq("ok")
    st = L["price_status"]
    rep.add(snap, "QA04", (~price_ok).sum(), price_ok.sum(),
            note=f"missing={st.eq('missing').sum()} parse_error={st.eq('parse_error').sum()} "
                 f"domain_error={st.eq('domain_error').sum()} price_iqr_flag={L['price_iqr_flag'].sum()}",
            kpi="KPI1/KPI4 giá trung vị toàn mẫu", before=L["price_parsed"].median(), after=L["price_num"].median())

    # QA05 amenities
    L["has_wifi"], L["has_kitchen"] = parse_amenities(L["amenities"])
    am_ok = L["has_wifi"].notna()
    both = (L["has_wifi"].fillna(False) & L["has_kitchen"].fillna(False)).sum()
    rep.add(snap, "QA05", (~am_ok).sum(), am_ok.sum(),
            kpi="KPI2 toàn mẫu", before=pct1(both, len(L)), after=pct1(both, am_ok.sum()))   # trước QA: NA tính như False

    # QA06 nhãn nhóm (thêm cột chuẩn hoá)
    L["borough"] = text(L, "neighbourhood_group_cleansed")
    L["neighbourhood"] = text(L, "neighbourhood_cleansed")
    L["room_type_std"] = text(L, "room_type")
    L["room_type_ok"] = L["room_type_std"].isin(q["allowed_room_types"])
    L["borough_ok"], L["neigh_ok"] = L["borough"].ne(""), L["neighbourhood"].ne("")
    labels_ok = L["room_type_ok"] & L["borough_ok"] & L["neigh_ok"]
    rep.add(snap, "QA06", (~labels_ok).sum(), labels_ok.sum(),
            note=f"room_type_sai={(~L['room_type_ok']).sum()} thiếu_quận={(~L['borough_ok']).sum()} thiếu_khu_phố={(~L['neigh_ok']).sum()}")

    # QA07 Superhost
    sh = text(L, "host_is_superhost").str.lower()
    L["is_superhost"] = pd.Series(pd.NA, index=L.index, dtype="boolean").mask(sh.eq("t"), True).mask(sh.eq("f"), False)
    known = L["is_superhost"].notna()
    rep.add(snap, "QA07", (~known).sum(), known.sum(),
            kpi="KPI5 toàn mẫu", before=pct1(L["is_superhost"].eq(True).sum(), len(L)),
            after=pct1(L["is_superhost"].eq(True).sum(), known.sum()))              # trước QA: NA tính như False
    return L


def qa_calendar(C, L, snap, cfg, rep):
    k = cfg["kpi"]
    C, rej = split_keys(C, ["listing_id", "date"])
    rep.reject("calendar", rej)
    rep.add(snap, "QA02", len(rej), len(C), note=f"calendar: {reasons(rej)}")
    C, rej = drop_orphans(C, L)
    rep.reject("calendar", rej)
    rep.add(snap, "QA03", len(rej), len(C), note="table=calendar")

    # QA08: chuẩn hoá ngày, trạng thái lịch, giới hạn số đêm
    d = pd.to_datetime(text(C, "date"), format="%Y-%m-%d", errors="coerce")
    C["date_iso"] = d.dt.strftime("%Y-%m-%d")
    av = text(C, "available").str.lower()
    C["available_state"] = np.where(av.eq("t"), "T", np.where(av.eq("f"), "F", "U"))
    mn, mx = (pd.to_numeric(text(C, c).replace("", np.nan), errors="coerce") for c in ("minimum_nights", "maximum_nights"))
    is_int = lambda x: (x > 0) & (x == np.floor(x))
    valid = is_int(mn) & is_int(mx) & (mn <= mx)
    C["constraints_state"] = np.where(~valid, "U", np.where((mn <= k["stay_nights"]) & (k["stay_nights"] <= mx), "T", "F"))
    start = pd.Timestamp(snap) + pd.Timedelta(days=1)                     # cửa sổ: snapshot+1 ... snapshot+window_days
    end = pd.Timestamp(snap) + pd.Timedelta(days=k["window_days"])
    C["in_window"] = (d >= start) & (d <= end)
    C["kpi3_day_eligible"] = d.notna() & C["in_window"]
    present = C.loc[C["kpi3_day_eligible"], ["listing_id", "date_iso"]].drop_duplicates().shape[0]
    bad = d.isna() | C["available_state"].eq("U") | C["constraints_state"].eq("U")
    rep.add(snap, "QA08", bad.sum(), C["kpi3_day_eligible"].sum(),
            note=f"cửa sổ {start.date()}..{end.date()}; ngày thiếu trong cửa sổ={len(L) * k['window_days'] - present}")
    return C


def qa_reviews(R, L, snap, cfg, rep):
    llm = cfg["llm"]
    R, rej = split_keys(R, ["id"])
    rep.reject("reviews", rej)
    rep.add(snap, "QA02", len(rej), len(R), note=f"reviews: {reasons(rej)}")
    R, rej = drop_orphans(R, L)
    rep.reject("reviews", rej)
    rep.add(snap, "QA03", len(rej), len(R), note="table=reviews")

    # QA09: nguồn review cố định
    R["comment_text"] = clean_text(R["comments"], llm.get("max_chars_per_review", 1200))
    R["comment_ok"] = R["comment_text"].ne("")
    assigned = text(R, "assigned_listing_id")      # cặp review-listing được giao (rỗng = tệp phân công không có listing_id)
    R["listing_pair_ok"] = text(R, "listing_id").ne("") & (assigned.eq("") | text(R, "listing_id").eq(assigned))
    rooms = L[L["room_type_ok"]].set_index("id")["room_type_std"]
    R["room_type_std"] = text(R, "listing_id").map(rooms).fillna("")
    R["llm_source_eligible"] = R["mau_llm"] & R["comment_ok"] & R["listing_pair_ok"] & R["room_type_std"].ne("")
    n_llm, n_hand, hand_outside = int(R["mau_llm"].sum()), int(R["nhan_tay"].sum()), int((R["nhan_tay"] & ~R["mau_llm"]).sum())
    count_ok = n_llm == llm["sample_size"] and n_hand == llm["hand_label_size"] and hand_outside == 0
    n_good = int(R["llm_source_eligible"].sum())
    status = "blocked" if n_good == 0 else ("pass" if count_ok and n_good == n_llm else "warning")
    rep.add(snap, "QA09", n_llm - n_good, n_good, status=status,
            note=f"mau_llm={n_llm} (cần {llm['sample_size']}) nhan_tay={n_hand} (cần {llm['hand_label_size']}) nhan_tay_ngoai_mau={hand_outside}")
    return R


def check_required(snap, tables, rep):
    """QA01: thiếu cột bắt buộc thì dừng ngay (không để KPI chạy tiếp với dữ liệu thiếu)."""
    missing, blocked, n_ok = [], set(), 0
    for table, df in tables.items():
        for col, kpis in REQUIRED[table].items():
            if col in df.columns:
                n_ok += 1
            else:
                missing.append(f"{table}.{col}")
                blocked.add(kpis)
    if missing:
        sys.exit(f"QA01 {snap}: thiếu cột {', '.join(missing)}; KPI bị chặn: {'; '.join(sorted(blocked))}")
    rep.add(snap, "QA01", 0, n_ok, status="pass")


# ---------------------------------------------------------------- chạy
def run_pre(cfg):
    lids, manifest = read_assignments(cfg)
    rids, info = set(manifest["review_id"]), manifest.set_index("review_id")
    rep, need = Report(), tables_snapshots(cfg)
    for snap in cfg["snapshots"]:
        raw = {"listings": filter_table(raw_file(snap, "listings"), "id", lids, LIST_COLS)}
        if snap in need["calendar"]:
            raw["calendar"] = filter_table(raw_file(snap, "calendar"), "listing_id", lids, CAL_COLS)
        if snap in need["reviews"]:
            raw["reviews"] = filter_table(raw_file(snap, "reviews"), "id", rids, REVIEW_COLS)
        check_required(snap, raw, rep)
        if len(raw["listings"]) < len(lids):
            log.warning("%s: thiếu %d/%d listing của nhóm trong dữ liệu", snap, len(lids) - len(raw["listings"]), len(lids))
        out = ensure_dir(PROC / snap)
        L = qa_listings(raw["listings"], snap, cfg, rep)
        L.to_csv(clean_file(snap, "listings"), index=False)
        if "calendar" in raw:
            qa_calendar(raw["calendar"], L, snap, cfg, rep).to_csv(clean_file(snap, "calendar"), index=False)
        if "reviews" in raw:
            R = raw["reviews"]
            for col in ("assigned_listing_id", "mau_llm", "nhan_tay"):
                R[col] = R["id"].map(info[col])
            R[["mau_llm", "nhan_tay"]] = R[["mau_llm", "nhan_tay"]].fillna(False).astype(bool)
            qa_reviews(R, L, snap, cfg, rep).to_csv(clean_file(snap, "reviews"), index=False)
        rep.flush(out)
    path = ensure_dir(REPORTS) / "qa_report.csv"
    pd.DataFrame(rep.rows, columns=REPORT_COLUMNS).to_csv(path, index=False)
    log.info("QA (trước LLM) xong: %d dòng -> %s", len(rep.rows), path)


def run_post(cfg):
    """QA10: kiểm tra kết quả LLM. Tạo llm_clean.csv.gz và thêm dòng QA10 vào qa_report.csv."""
    snap, rooms = snapshot_of(cfg, "llm_snapshot_index"), cfg["kpi"]["llm_room_types"]
    R = read_clean(clean_file(snap, "reviews"))
    src = R[R["llm_source_eligible"]][["id", "listing_id", "room_type_std", "comment_text"]].rename(columns={"id": "review_id"})
    pred_path = PROC / "llm_predictions.csv.gz"
    P = read_text(pred_path) if pred_path.exists() else pd.DataFrame(columns=["review_id"])
    P = P.drop_duplicates()                                                   # trùng hoàn toàn: giữ 1 bản
    clash = set(P.loc[P.duplicated("review_id", keep=False), "review_id"])    # cùng review_id nhưng khác nội dung: xung đột
    P = P[~P["review_id"].isin(clash)].rename(columns={"listing_id": "pred_listing_id"})
    m = src.merge(P, on="review_id", how="left")
    get = lambda c: m[c].fillna("") if c in m.columns else pd.Series("", index=m.index)
    m["prediction_ok"] = (get("status").eq("ok") & get("snapshot").eq(snap) & get("pred_listing_id").eq(m["listing_id"])
                          & get("text_hash").eq(m["comment_text"].map(text_hash)) & get("model").ne("")
                          & ~m["review_id"].isin(clash))
    m["kpi6_eligible"] = m["prediction_ok"]       # sentiment/aspect đã được lược đồ trong llm.py ép đúng miền
    m.to_csv(ensure_dir(PROC) / "llm_clean.csv.gz", index=False)

    n_good = int(m["kpi6_eligible"].sum())
    status = "blocked" if len(m) and n_good == 0 else ("pass" if n_good == len(m) else "warning")
    in_rooms = m[m["room_type_std"].isin(rooms)]
    neg = lambda d: get("sentiment").loc[d.index].eq("negative").sum()
    kept = in_rooms[in_rooms["kpi6_eligible"]]
    rep_path = REPORTS / "qa_report.csv"
    rep = pd.read_csv(rep_path) if rep_path.exists() else pd.DataFrame(columns=REPORT_COLUMNS)
    rep = rep[rep["rule"] != "QA10"]
    r = Report()
    r.add(snap, "QA10", len(m) - n_good, n_good, status=status,
          note=f"review nguồn={len(m)} có prediction={int(get('status').eq('ok').sum())} xung_đột={len(clash)}",
          kpi="KPI6 toàn mẫu", before=pct1(neg(in_rooms), len(in_rooms)), after=pct1(neg(kept), len(kept)))
    pd.concat([rep, pd.DataFrame(r.rows, columns=REPORT_COLUMNS)], ignore_index=True).to_csv(rep_path, index=False)
    log.info("QA10 xong: %d/%d review đủ điều kiện KPI 6/7", n_good, len(m))


def main(cfg, post=False):
    (run_post if post else run_pre)(cfg)


if __name__ == "__main__":
    cli(main)
