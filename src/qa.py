"""QA: chuẩn hoá dữ liệu và tạo cờ hợp lệ. KHÔNG tính KPI (việc đó của kpi.py).

Nguyên tắc (theo QA_SPEC_10_RULES.md):
- Không sửa data/raw và dữ liệu lọc đầu vào; giữ nguyên cột gốc, chỉ THÊM cột dẫn xuất.
- Không dropna toàn bảng, không tự điền dữ liệu thiếu. Mỗi KPI tự chọn cờ nó cần.
- Thiếu / lỗi định dạng / sai miền / chưa xác định (U) được phân biệt khi cần.

Hai lần chạy:  run_pre  (trước LLM: QA01-QA09)   và   run_post  (sau LLM: QA10).
Đầu ra: data/processed/<mốc>/{listings,calendar,reviews}_clean.csv.gz, llm_clean.csv.gz, reports/qa_report.csv
"""
from __future__ import annotations

import hashlib
import json
import re

import numpy as np
import pandas as pd

from src.utils import (ensure_dir, folder, get_logger, read_clean, read_text, snapshot_of, table_file,
                       tables_snapshots)

log = get_logger("qa")

# mã -> (tên, điều kiện, lý do, hành động)
RULES = {
    "QA01": ("Cột bắt buộc", "thiếu cột mà KPI cần", "không có dữ liệu nguồn thì không tính được KPI",
             "ghi blocked cho KPI liên quan; không tạo cột giả"),
    "QA02": ("Khoá và bản ghi trùng", "khoá thiếu/sai, trùng hoàn toàn, hoặc cùng khoá nhưng nội dung khác",
             "tránh tính lặp, đếm sai, nối nhầm",
             "analysis_row: trùng hoàn toàn chỉ tính 1 bản; khoá xung đột gắn conflict và không dùng (không giữ bản đầu/cuối)"),
    "QA03": ("Ghép bảng đúng mốc", "listing_id của calendar/reviews không ghép được với listings cùng mốc",
             "không được lấy nhầm thông tin listing/loại phòng", "join_status = matched / orphan / parent_conflict; KPI chỉ dùng matched"),
    "QA04": ("Giá", "giá thiếu, sai định dạng, không dương; hoặc giá dương nhưng ngoại lai (IQR)",
             "KPI giá cần giá dương hợp lệ, nhưng không tự loại giá cao có thật",
             "price_num chỉ giữ giá hợp lệ; giá ngoại lai chỉ gắn price_iqr_flag, vẫn tính"),
    "QA05": ("Amenities", "amenities thiếu hoặc không đọc được thành danh sách",
             "không xác định được Wi-Fi/Kitchen", "has_wifi/has_kitchen = T/F; thiếu hoặc lỗi = U (không coi là F)"),
    "QA06": ("Nhãn nhóm", "room_type ngoài danh sách cho phép, hoặc thiếu quận/khu phố",
             "không nhóm đúng đối tượng", "gắn *_ok; chỉ loại khỏi KPI cần nhãn đó; không xoá dòng"),
    "QA07": ("Superhost", "host_is_superhost không phải t/f hoặc thiếu", "không xác định có phải Superhost",
             "superhost_state = T/F/U; KPI 5 chỉ dùng T và F"),
    "QA08": ("Calendar và ràng buộc 3 đêm", "ngày sai; available không phải t/f; min/max không hợp lệ; thiếu ngày trong cửa sổ",
             "không đoán khả năng đặt phòng từ dữ liệu sai/thiếu",
             "available_state, constraints_state (T/F/U); giữ cả ngày U; không thêm ngày thiếu; không xét chuỗi 3 đêm ở đây"),
    "QA09": ("Nguồn review", "không đúng 1.000 review LLM + 100 nhãn tay, review rỗng, sai cặp review-listing, không ghép được loại phòng",
             "phải giữ đúng mẫu cố định", "llm_source_eligible; không tự chọn review thay thế"),
    "QA10": ("Kết quả LLM", "prediction thiếu/xung đột/sai ID-mốc-nội dung; sentiment hoặc cặp aspect ngoài giá trị cho phép",
             "không tính KPI từ kết quả không đáng tin", "prediction_ok, kpi6_eligible, <aspect>_ok"),
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
WIFI = re.compile(r"^(fast )?wi-?fi( [-–] \d+(\.\d+)? ?mbps)?$")   # wifi, fast wifi - 75 mbps; KHÔNG khớp pocket wifi, ...over wifi...


class Report:
    def __init__(self):
        self.rows = []

    def add(self, snap, rule, n_affected, n_valid, status=None, note=""):
        name, cond, reason, action = RULES[rule]
        if status is None:
            status = "pass" if n_affected == 0 else "warning"
        self.rows.append({"snapshot": snap, "rule": rule, "name": name, "condition": cond, "reason": reason,
                          "action": action, "n_affected": int(n_affected), "n_valid": int(n_valid),
                          "status": status, "note": note, "kpi": "", "kpi_before": np.nan, "kpi_after": np.nan})


def text(df, col):
    """Cột dạng chuỗi đã bỏ khoảng trắng; thiếu -> chuỗi rỗng (cột không tồn tại cũng cho chuỗi rỗng)."""
    s = df[col] if col in df.columns else pd.Series("", index=df.index)
    return s.fillna("").astype(str).str.strip()


def mark_keys(df, keys):
    """QA02: thêm key_valid, dup_exact, conflict, analysis_row (gọi TRƯỚC khi thêm cột dẫn xuất)."""
    df = df.copy()
    if not all(k in df.columns for k in keys):
        for c in ("key_valid", "dup_exact", "conflict", "analysis_row"):
            df[c] = False
        return df
    valid = pd.concat([text(df, k).ne("") for k in keys], axis=1).all(axis=1)
    dup_exact = df.duplicated(keep="first")                 # bản sao trùng HOÀN TOÀN (cả nội dung)
    first = df[~dup_exact & valid]
    clash = first[first.duplicated(subset=keys, keep=False)][keys].drop_duplicates()   # cùng khoá, khác nội dung
    conflict = df[keys].merge(clash.assign(_c=True), on=keys, how="left")["_c"].eq(True).to_numpy()
    df["key_valid"], df["dup_exact"], df["conflict"] = valid, dup_exact, conflict
    df["analysis_row"] = valid & ~dup_exact & ~conflict
    return df


def join_status(child_ids, listings):
    """QA03: ghép 'nhiều dòng con - một listing' bằng tập ID duy nhất nên không nhân dòng."""
    ok = set(listings.loc[listings["analysis_row"], "id"])
    bad = set(listings.loc[listings["conflict"], "id"])
    return pd.Series(np.where(child_ids.isin(bad), "parent_conflict", np.where(child_ids.isin(ok), "matched", "orphan")),
                     index=child_ids.index)


def parse_price(s):
    """'$1,250.00' -> 1250.0. Trả về (số hoặc NaN, trạng thái ok/missing/parse_error/domain_error)."""
    txt = s.fillna("").astype(str).str.replace(r"[$,\s]", "", regex=True)
    num = pd.to_numeric(txt.replace("", np.nan), errors="coerce").astype(float)
    status = np.select([txt.eq(""), num.isna(), (num <= 0) | ~np.isfinite(num)],
                       ["missing", "parse_error", "domain_error"], default="ok")
    return num, pd.Series(status, index=s.index)


def parse_amenities(s):
    """Danh sách tiện nghi JSON -> (amenities_status, has_wifi, has_kitchen); T/F/U."""
    status, wifi, kitchen = [], [], []
    for x in s.fillna("").astype(str):
        try:
            items = json.loads(x) if x.strip() else None
        except ValueError:
            items = "error"
        if items is None:
            st = "missing"
        elif not isinstance(items, list) or not all(isinstance(i, str) for i in items):
            st = "parse_error"
        else:
            st = "ok"
        status.append(st)
        if st == "ok":
            names = [i.strip().lower() for i in items]
            wifi.append("T" if any(WIFI.match(n) for n in names) else "F")
            kitchen.append("T" if "kitchen" in names else "F")      # khớp nguyên tên, không tìm chuỗi con
        else:
            wifi.append("U")
            kitchen.append("U")
    return status, wifi, kitchen


# ---------------------------------------------------------------- từng bảng
def qa_listings(L, snap, cfg, rep):
    q = cfg["qa"]
    L = mark_keys(L, ["id"])
    a = L["analysis_row"]
    rep.add(snap, "QA02", (~a).sum(), a.sum(), note=f"listings: dup_exact={L['dup_exact'].sum()} conflict={L['conflict'].sum()} key_invalid={(~L['key_valid']).sum()}")

    # QA04 giá
    L["price_parsed"], L["price_status"] = parse_price(L["price"] if "price" in L.columns else pd.Series("", index=L.index))
    L["price_num"] = L["price_parsed"].where(L["price_status"].eq("ok"))
    q1, q3 = L.loc[a, "price_num"].quantile([0.25, 0.75])
    L["price_iqr_flag"] = (L["price_num"] < q1 - 1.5 * (q3 - q1)) | (L["price_num"] > q3 + 1.5 * (q3 - q1))
    price_ok = a & L["price_status"].eq("ok")
    rep.add(snap, "QA04", (a & ~price_ok).sum(), price_ok.sum(),
            note=f"missing={(a & L['price_status'].eq('missing')).sum()} parse_error={(a & L['price_status'].eq('parse_error')).sum()} "
                 f"domain_error={(a & L['price_status'].eq('domain_error')).sum()} price_iqr_flag={(a & L['price_iqr_flag']).sum()}")

    # QA05 amenities
    L["amenities_status"], L["has_wifi"], L["has_kitchen"] = parse_amenities(L["amenities"] if "amenities" in L.columns else pd.Series("", index=L.index))
    am_ok = a & L["amenities_status"].eq("ok")
    rep.add(snap, "QA05", (a & ~am_ok).sum(), am_ok.sum())

    # QA06 nhãn nhóm (giữ cột gốc, thêm cột chuẩn hoá)
    L["borough"] = text(L, "neighbourhood_group_cleansed")
    L["neighbourhood"] = text(L, "neighbourhood_cleansed")
    L["room_type_std"] = text(L, "room_type")
    L["room_type_ok"] = L["room_type_std"].isin(q["allowed_room_types"])
    L["borough_ok"], L["neigh_ok"] = L["borough"].ne(""), L["neighbourhood"].ne("")
    labels_ok = a & L["room_type_ok"] & L["borough_ok"] & L["neigh_ok"]
    rep.add(snap, "QA06", (a & ~labels_ok).sum(), labels_ok.sum(),
            note=f"room_type_sai={(a & ~L['room_type_ok']).sum()} thiếu_quận={(a & ~L['borough_ok']).sum()} thiếu_khu_phố={(a & ~L['neigh_ok']).sum()}")

    # QA07 Superhost
    sh = text(L, "host_is_superhost").str.lower()
    L["superhost_state"] = np.where(sh.eq("t"), "T", np.where(sh.eq("f"), "F", "U"))
    rep.add(snap, "QA07", (a & L["superhost_state"].eq("U")).sum(), (a & L["superhost_state"].ne("U")).sum())

    # cờ đủ điều kiện cho từng KPI
    group_ok = L["borough_ok"] & L["room_type_ok"]
    L["kpi1_eligible"] = price_ok & group_ok
    L["kpi2_eligible"] = am_ok & group_ok
    L["kpi4_eligible"] = price_ok & group_ok & L["neigh_ok"]
    L["kpi5_eligible"] = a & L["superhost_state"].ne("U")
    return L


def qa_calendar(C, L, snap, cfg, rep):
    k = cfg["kpi"]
    C = mark_keys(C, ["listing_id", "date"])
    a = C["analysis_row"]
    rep.add(snap, "QA02", (~a).sum(), a.sum(), note=f"calendar: dup_exact={C['dup_exact'].sum()} conflict={C['conflict'].sum()}")
    C["join_status"] = join_status(text(C, "listing_id"), L)
    matched = C["join_status"].eq("matched")
    rep.add(snap, "QA03", (a & ~matched).sum(), (a & matched).sum(), note="table=calendar")

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
    C["kpi3_day_eligible"] = a & matched & d.notna() & C["in_window"]
    n_listings = L["analysis_row"].sum()
    present = C.loc[C["kpi3_day_eligible"], ["listing_id", "date_iso"]].drop_duplicates().shape[0]
    bad = (d.isna() | C["available_state"].eq("U") | C["constraints_state"].eq("U")) & a
    rep.add(snap, "QA08", bad.sum(), C["kpi3_day_eligible"].sum(),
            note=f"cửa sổ {start.date()}..{end.date()}; ngày thiếu trong cửa sổ={n_listings * k['window_days'] - present}")
    return C


def qa_reviews(R, L, snap, cfg, rep):
    llm = cfg["llm"]
    R = mark_keys(R, ["id"])
    a = R["analysis_row"]
    rep.add(snap, "QA02", (~a).sum(), a.sum(), note=f"reviews: dup_exact={R['dup_exact'].sum()} conflict={R['conflict'].sum()}")
    R["join_status"] = join_status(text(R, "listing_id"), L)
    matched = R["join_status"].eq("matched")
    rep.add(snap, "QA03", (a & ~matched).sum(), (a & matched).sum(), note="table=reviews")

    # QA09: nguồn review cố định
    R["comment_text"] = (text(R, "comments").str.replace(r"<br\s*/?>", " ", regex=True)
                         .str.replace(r"\s+", " ", regex=True).str.strip())
    R["comment_ok"] = R["comment_text"].ne("")
    assigned = text(R, "assigned_listing_id")      # cặp review-listing được giao (rỗng = tệp phân công không có listing_id)
    R["listing_pair_ok"] = text(R, "listing_id").ne("") & (assigned.eq("") | text(R, "listing_id").eq(assigned))
    rooms = L.loc[L["analysis_row"] & L["room_type_ok"]].set_index("id")["room_type_std"]
    R["room_type_std"] = text(R, "listing_id").map(rooms).fillna("")
    in_llm = text(R, "mau_llm").str.lower().eq("true")
    in_hand = text(R, "nhan_tay").str.lower().eq("true")
    R["mau_llm"], R["nhan_tay"] = in_llm, in_hand
    R["llm_source_eligible"] = in_llm & a & R["comment_ok"] & R["listing_pair_ok"] & matched & R["room_type_std"].ne("")
    n_llm, n_hand, hand_outside = int(in_llm.sum()), int(in_hand.sum()), int((in_hand & ~in_llm).sum())
    count_ok = n_llm == llm["sample_size"] and n_hand == llm["hand_label_size"] and hand_outside == 0
    n_good = int(R["llm_source_eligible"].sum())
    status = "blocked" if n_good == 0 else ("pass" if count_ok and n_good == n_llm else "warning")
    rep.add(snap, "QA09", n_llm - n_good, n_good, status=status,
            note=f"mau_llm={n_llm} (cần {llm['sample_size']}) nhan_tay={n_hand} (cần {llm['hand_label_size']}) nhan_tay_ngoai_mau={hand_outside}")
    return R


def check_required(snap, tables, rep):
    """QA01: báo cột thiếu và KPI bị chặn."""
    missing, blocked = [], set()
    n_ok = 0
    for table, df in tables.items():
        for col, kpis in REQUIRED[table].items():
            if col in df.columns:
                n_ok += 1
            else:
                missing.append(f"{table}.{col}")
                blocked.add(kpis)
    rep.add(snap, "QA01", len(missing), n_ok, status="blocked" if missing else "pass",
            note=("thiếu " + ", ".join(missing) + "; KPI bị chặn: " + "; ".join(sorted(blocked))) if missing else "")


# ---------------------------------------------------------------- chạy
def run_pre(cfg):
    rep, need = Report(), tables_snapshots(cfg)
    for snap in cfg["snapshots"]:
        raw = {"listings": read_text(table_file(cfg, "interim", snap, "listings_filtered"))}
        if snap in need["calendar"]:
            raw["calendar"] = read_text(table_file(cfg, "interim", snap, "calendar_filtered"))
        if snap in need["reviews"]:
            raw["reviews"] = read_text(table_file(cfg, "interim", snap, "reviews_filtered"))
        check_required(snap, raw, rep)
        out = ensure_dir(folder(cfg, "processed", snap))
        L = qa_listings(raw["listings"], snap, cfg, rep)
        L.to_csv(out / "listings_clean.csv.gz", index=False)
        if "calendar" in raw:
            qa_calendar(raw["calendar"], L, snap, cfg, rep).to_csv(out / "calendar_clean.csv.gz", index=False)
        if "reviews" in raw:
            qa_reviews(raw["reviews"], L, snap, cfg, rep).to_csv(out / "reviews_clean.csv.gz", index=False)
    path = ensure_dir(folder(cfg, "reports")) / "qa_report.csv"
    pd.DataFrame(rep.rows, columns=REPORT_COLUMNS).to_csv(path, index=False)
    log.info("QA (trước LLM) xong: %d dòng -> %s", len(rep.rows), path)


def text_hash(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def run_post(cfg):
    """QA10: kiểm tra kết quả LLM. Tạo llm_clean.csv.gz và thêm dòng QA10 vào qa_report.csv."""
    snap = snapshot_of(cfg, "llm_snapshot_index")
    aspects, allowed = list(cfg["llm"]["aspects"]), set(cfg["llm"]["allowed_sentiments"])
    R = read_clean(table_file(cfg, "processed", snap, "reviews_clean"))
    src = R[R["llm_source_eligible"]][["id", "listing_id", "room_type_std", "comment_text"]].rename(columns={"id": "review_id"})
    pred_path = folder(cfg, "processed") / "llm_predictions.csv.gz"
    P = read_text(pred_path) if pred_path.exists() else pd.DataFrame(columns=["review_id"])
    P = P.drop_duplicates()                                                   # trùng hoàn toàn: giữ 1 bản
    clash = set(P.loc[P.duplicated("review_id", keep=False), "review_id"])    # cùng review_id nhưng khác nội dung: xung đột
    P = P[~P["review_id"].isin(clash)].rename(columns={"listing_id": "pred_listing_id"})
    m = src.merge(P, on="review_id", how="left")
    get = lambda c: m[c].fillna("") if c in m.columns else pd.Series("", index=m.index)
    m["prediction_ok"] = (get("status").eq("ok") & get("snapshot").eq(snap) & get("pred_listing_id").eq(m["listing_id"])
                          & get("text_hash").eq(m["comment_text"].map(text_hash)) & get("model").ne("")
                          & ~m["review_id"].isin(clash))
    m["sentiment_ok"] = get("sentiment").isin(allowed)
    m["kpi6_eligible"] = m["prediction_ok"] & m["sentiment_ok"]
    bad_pairs = 0
    for a in aspects:                                                          # mỗi cặp aspect chỉ được là 1 hoặc ô trống
        pair_ok = pd.concat([get(f"{a}_positive").isin(["", "1"]), get(f"{a}_negative").isin(["", "1"])], axis=1).all(axis=1)
        m[f"{a}_ok"] = m["prediction_ok"] & pair_ok
        bad_pairs += int((m["prediction_ok"] & ~pair_ok).sum())
    ensure_dir(folder(cfg, "processed"))
    m.to_csv(folder(cfg, "processed") / "llm_clean.csv.gz", index=False)

    n_good = int(m["kpi6_eligible"].sum())
    status = "blocked" if len(m) and n_good == 0 else ("pass" if n_good == len(m) else "warning")
    rep_path = folder(cfg, "reports") / "qa_report.csv"
    rep = pd.read_csv(rep_path) if rep_path.exists() else pd.DataFrame(columns=REPORT_COLUMNS)
    rep = rep[rep["rule"] != "QA10"]
    r = Report()
    r.add(snap, "QA10", len(m) - n_good, n_good, status=status,
          note=f"review nguồn={len(m)} có prediction={int(get('status').eq('ok').sum())} xung_đột={len(clash)} cặp_aspect_sai={bad_pairs}")
    pd.concat([rep, pd.DataFrame(r.rows, columns=REPORT_COLUMNS)], ignore_index=True).to_csv(rep_path, index=False)
    log.info("QA10 xong: %d/%d review đủ điều kiện KPI 6/7", n_good, len(m))
