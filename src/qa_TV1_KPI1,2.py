"""QA chung + QA riêng cho KPI 1 và KPI 2 (listings). Gắn cờ, không xóa dòng.

Đầu vào : data/interim/<mốc>/listings_filtered.csv.gz
Đầu ra  : data/processed/manifest_kpi1.csv   (KPI 1: chỉ mốc kpi1_snapshot)
          data/processed/manifest_kpi2.csv   (KPI 2: mọi mốc trong snapshots)
              -> truy vết từng listing: cột gốc + cột chuẩn hóa + cờ boolean + exclude_<kpi>
          reports/qa/qa_tv1.csv                 báo cáo QA (rule, điều kiện, lý do, số dòng, tác động), 26 cột
          reports/qa/standardization_audit.csv  ô nào đổi giá trị sau chuẩn hóa, đổi thế nào, vì sao
          reports/qa/pipeline_metadata.json     tái lập: run_id, version, SHA-256 nguồn, cấu hình
Chạy    : python qa.py --config config/newyork.yaml
(Q09 không dùng vì KPI 1 và 2 chỉ đọc một bảng listings, không có phép merge.)
"""
# ----------KHỐI 1: IMPORT-------------
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

# -----------KHỐI 2: HẰNG SỐ------------
log = logging.getLogger("qa")

RULE_VERSION = "qa-v1.1"
MAP_VERSION = "map_v1"                                    # phiên bản bảng ánh xạ (room_type, quận, tiện nghi); đổi map thì tăng số
POCKET_WIFI_POLICY = "not_counted_as_wifi"                # Pocket wifi không được tính thay Wi-Fi
PRICE_SOURCE = "listings.price"                           # KPI 1 dùng price của listings, không dùng price_quote
# Các ngưỡng (iqr_multiplier, max_trip_nights, kpi1_snapshot, min_coverage_pct) nằm trong khối qa của yaml.

# Cột bắt buộc của từng KPI. Thiếu cột ở mốc nào thì mốc đó bị cờ Q02.
KPI_COLS = {
    "kpi1": ["id", "price", "neighbourhood_group_cleansed", "room_type"],
    "kpi2": ["id", "amenities", "neighbourhood_group_cleansed", "room_type"],
}
# Cột chỉ để truy vết giá/quote của KPI 1 (không bắt buộc)
QUOTE_COLS = ["last_scraped", "source", "price_quote_checkin_date", "price_quote_checkout_date",
              "price_quote_price_per_night", "price_quote_raw"]

# Token NA chuẩn của pandas (đã casefold). Ô rỗng hoặc chỉ có khoảng trắng cũng là missing.
NA_TOKENS = {"", "#n/a", "#n/a n/a", "#na", "-1.#ind", "-1.#qnan", "-nan", "1.#ind",
             "1.#qnan", "<na>", "n/a", "na", "null", "nan", "none"}
ROOM_TYPES = ["Entire home/apt", "Private room", "Shared room", "Hotel room"]
BOROUGHS = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
MONEY_RE = r"-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"                      # $1,250.00 | 1250 | -5
WIFI_RE = re.compile(r"(?:fast )?wifi(?: - \d+(?:\.\d+)? mbps)?")           # Wifi | Fast wifi | Wifi - 41 Mbps

# Mỗi quy tắc: (mã, cột cờ trong manifest, điều kiện, lý do, hành động, có loại khỏi KPI không)
RULES = [
    ("Q01", "flag_q01_missing", "ô rỗng/whitespace/token NA ở trường bắt buộc", "thiếu dữ liệu", "FLAG", False),
    ("Q02", "flag_q02_schema", "thiếu cột bắt buộc ở mốc", "schema không đủ", "FLAG", False),
    ("Q03", "flag_q03_parse_error", "giá sai cú pháp (parse_error) hoặc không hữu hạn (nonfinite)", "sai cú pháp", "FLAG + EXCLUDE_FROM_KPI", True),
    ("Q03", "flag_q03_domain_error", "giá <= 0 (nonpositive) hoặc ID không khớp [0-9]+", "ngoài miền", "FLAG + EXCLUDE_FROM_KPI", True),
    ("Q04", "flag_q04_date_error", "ngày sai YYYY-MM-DD, scrape/quote trước nhãn mốc, check-out <= check-in", "ngày không hợp lệ", "FLAG", False),
    ("Q05", "flag_q05_invalid_token", "room_type/quận ngoài miền hoặc casing/whitespace lạ", "token lạ", "FLAG", False),
    ("Q06", "flag_q06_duplicate", "trùng id trong cùng mốc (mọi dòng của nhóm trùng)", "trùng khóa", "FLAG", False),
    ("Q06", "flag_q06_extra_copy", "bản sao thừa của nhóm trùng giống hệt (giữ bản đầu)", "trùng cả dữ liệu", "FLAG + EXCLUDE_FROM_KPI", True),
    ("Q06", "flag_q06_conflict", "cùng id nhưng khác dữ liệu (loại cả nhóm)", "khóa xung đột", "FLAG + EXCLUDE_FROM_KPI", True),
    ("Q07", "flag_q07_repeated", "id xuất hiện ở nhiều mốc", "panel lặp", "FLAG", False),
    ("Q08", "flag_q08_orphan", "ID thiếu/sai hoặc chưa xác định quận/loại phòng", "không xác định nhóm", "FLAG + EXCLUDE_FROM_KPI", True),
    ("Q10", "flag_q10_outlier_iqr", "giá ngoài fence IQR [Q1-k*IQR, Q3+k*IQR], k = iqr_multiplier", "ngoại lai", "FLAG", False),
    ("K1-01", "flag_k1_price_missing", "price rỗng", "thiếu giá", "FLAG + EXCLUDE_FROM_KPI", True),
    ("K1-06", "flag_k1_quote_mismatch", "quote thiếu ngày hoặc khác price", "quote không khớp chuyến ngắn", "FLAG", False),
    ("K2-01", "flag_k2_amenities_missing", "amenities rỗng (khác '[]')", "không biết khai báo", "FLAG", False),
    ("K2-02", "flag_k2_invalid_json", "amenities không phải JSON list[str]", "JSON lỗi", "FLAG + EXCLUDE_FROM_KPI", True),
]

QA_COLS = ["kpi", "snapshot", "dataset", "group_key", "rule_id", "condition", "reason", "action", "observation_unit",
           "affected_rows", "observations_before", "observations_after", "n_eligible", "coverage",
           "kpi_before", "kpi_after", "delta", "unit", "before_status", "after_status", "notes",
           "run_id", "rule_version", "decision_ref", "source_path", "source_sha256"]


# -----------KHỐI 3: ĐỌC DỮ LIỆU--------
def load_interim(cfg: dict, table: str, snapshots: list[str]) -> pd.DataFrame:
    """Đọc bảo toàn: mọi cột là chuỗi (ID không qua float), không tự đổi 'NA' thành NaN.
    Cột không có trong file sẽ thành NaN khi gộp mốc. Thiếu file của mốc nào thì báo lỗi ngay, không bỏ qua mốc."""
    root = Path(cfg.get("interim_dir", "data/interim"))
    parts = []
    for snap in snapshots:
        df = pd.read_csv(root / snap / f"{table}_filtered.csv.gz", dtype=str, keep_default_na=False,
                         na_filter=False, encoding="utf-8-sig")
        df.insert(0, "snapshot", snap)
        parts.append(df)
    return pd.concat(parts, ignore_index=True)


# -----------KHỐI 4: MANIFEST (CHUẨN HÓA + CỜ BOOLEAN)----
def read_amenities(text: str):
    """Trả về (trạng thái, danh sách tiện nghi hợp lệ đã chuẩn hóa, has_wifi, has_kitchen, has_pocket_wifi).
    '[]' là hợp lệ, không phải missing."""
    if text.strip().casefold() in NA_TOKENS:
        return "missing", None, pd.NA, pd.NA, pd.NA
    try:
        items = json.loads(text)
    except ValueError:
        items = None
    if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
        return "invalid", None, pd.NA, pd.NA, pd.NA
    tokens = set()                                   # set: tên lặp trong một listing chỉ tính một lần
    for x in items:
        x = unicodedata.normalize("NFKC", x).casefold()
        x = re.sub(r"[\u2010-\u2015\u2212]", "-", x)             # mọi loại gạch ngang -> '-'
        tokens.add(re.sub(r"\s*-\s*", " - ", " ".join(x.split())))
    wifi = any(WIFI_RE.fullmatch(t) for t in tokens)             # khớp toàn token: 'Sonos over WiFi...' không tính
    return "ok", sorted(tokens), wifi, "kitchen" in tokens, "pocket wifi" in tokens


def choose_final(df: pd.DataFrame) -> pd.DataFrame:
    """Q06: xử lý trùng id trong cùng mốc. So sánh MỌI cột gốc của dòng.
    - trùng cả dữ liệu : giữ bản đầu tiên, các bản sao còn lại bị loại (flag_q06_extra_copy)
    - cùng id, khác dữ liệu: loại TẤT CẢ dòng của id đó, không chọn bản nào (flag_q06_conflict)
    Chỉ đánh dấu, không xóa dòng khỏi manifest."""
    has_id = df["id"].fillna("").str.strip() != ""                 # id rỗng không tính là trùng (Q01/Q08 lo)
    same_id = has_id & df.duplicated(["snapshot", "id"], keep=False)
    row_hash = pd.util.hash_pandas_object(df.drop(columns="snapshot"), index=False)   # "dấu vân tay" của cả dòng
    versions = row_hash.groupby([df["snapshot"], df["id"]]).transform("nunique")      # số phiên bản khác nhau của cùng id
    return pd.DataFrame({"flag_q06_conflict": same_id & (versions > 1),
                         "flag_q06_extra_copy": same_id & (versions == 1) & df.duplicated(["snapshot", "id"], keep="first")})


def build_manifest(df: pd.DataFrame, kpi: str, qa_cfg: dict) -> pd.DataFrame:
    """Mỗi dòng listing: cột gốc + cột chuẩn hóa + cờ boolean + exclude_<kpi>. Không xóa dòng nào."""
    cols = KPI_COLS[kpi]
    m = df.reindex(columns=["snapshot"] + cols + (QUOTE_COLS if kpi == "kpi1" else [])).copy()
    absent = m[cols].isna()                          # NaN chỉ xuất hiện khi cột KHÔNG có trong file của mốc đó
    text = m.fillna("")
    miss = lambda c: text[c].str.strip().str.casefold().isin(NA_TOKENS)
    m["map_version"] = MAP_VERSION

    # --- QA chung ---
    m["flag_q01_missing"] = pd.concat([miss(c) for c in cols], axis=1).any(axis=1)          # Q01
    m["flag_q02_schema"] = absent.any(axis=1)                                               # Q02
    id_ok = text["id"].str.fullmatch(r"[0-9]+")                                             # Q03: ID là chuỗi, không trim, không đoán
    m["flag_q03_domain_error"] = ~miss("id") & ~id_ok
    m["room_type_clean"] = text["room_type"].str.strip().str.casefold().map({v.casefold(): v for v in ROOM_TYPES})   # Q05
    m["borough_clean"] = text["neighbourhood_group_cleansed"].str.strip().str.casefold().map({v.casefold(): v for v in BOROUGHS})
    m["flag_q05_invalid_token"] = ((~miss("room_type") & ~text["room_type"].isin(ROOM_TYPES))
                                   | (~miss("neighbourhood_group_cleansed") & ~text["neighbourhood_group_cleansed"].isin(BOROUGHS)))
    m["flag_q06_duplicate"] = ~miss("id") & m.duplicated(["snapshot", "id"], keep=False)    # Q06: mọi dòng thuộc nhóm trùng
    dup = choose_final(df)                                                                  # Q06: dòng nào bị loại
    m["flag_q06_conflict"], m["flag_q06_extra_copy"] = dup["flag_q06_conflict"], dup["flag_q06_extra_copy"]
    m["n_snapshots_seen"] = m.groupby("id")["snapshot"].transform("nunique").where(~miss("id"))      # Q07: id có mặt ở mấy mốc
    m["snapshots_seen"] = m.groupby("id")["snapshot"].transform(lambda s: "|".join(sorted(set(s)))).where(~miss("id"))
    m["flag_q07_repeated"] = m["n_snapshots_seen"] > 1                                      # panel lặp, không phải lỗi
    m["flag_q08_orphan"] = ~id_ok | m["room_type_clean"].isna() | m["borough_clean"].isna()  # Q08: chưa xác định nhóm

    if kpi == "kpi1":
        # --- Q03: giá. Kiểm cú pháp TRƯỚC khi bỏ $ và dấu phẩy. Tách rõ 4 loại: missing / parse_error / nonfinite / nonpositive ---
        ok_syntax = text["price"].str.fullmatch(MONEY_RE)
        num = pd.to_numeric(text["price"].where(ok_syntax).str.replace(r"[$,]", "", regex=True), errors="coerce")
        m["price_status"] = np.select([miss("price"), ~ok_syntax, ~np.isfinite(num), num <= 0],
                                      ["missing", "parse_error", "nonfinite", "nonpositive"], default="ok")
        m["price_num"] = num.where(m["price_status"] == "ok")                               # chỉ giá hữu hạn, > 0
        m["price_source"] = PRICE_SOURCE
        m["flag_k1_price_missing"] = m["price_status"] == "missing"
        m["flag_q03_parse_error"] = m["price_status"].isin(["parse_error", "nonfinite"])
        m["flag_q03_domain_error"] |= m["price_status"] == "nonpositive"
        # chiết khấu nằm trong price_quote_raw (JSON): lấy discount_amount để kiểm soát chiết khấu kỳ dài
        m["discount_amount"] = pd.to_numeric(text["price_quote_raw"].str.extract(r'"discount_amount":\s*"?(-?[\d.]+)')[0], errors="coerce")

        # --- Q04: ngày nghiêm YYYY-MM-DD; scrape/quote không được trước nhãn mốc. Scrape trễ là hợp lệ, không cờ ---
        snap = pd.to_datetime(m["snapshot"], format="%Y-%m-%d")
        m["flag_q04_date_error"] = False
        for c, new in [("last_scraped", "scrape_dt"), ("price_quote_checkin_date", "checkin_dt"), ("price_quote_checkout_date", "checkout_dt")]:
            ok = text[c].str.fullmatch(r"\d{4}-\d{2}-\d{2}")
            m[new] = pd.to_datetime(text[c].where(ok), format="%Y-%m-%d", errors="coerce")
            m["flag_q04_date_error"] |= ~miss(c) & m[new].isna()
        m["flag_q04_date_error"] |= (m["scrape_dt"] < snap) | (m["checkin_dt"] < snap) | (m["checkout_dt"] <= m["checkin_dt"])
        m["scrape_lag_days"] = (m["scrape_dt"] - snap).dt.days                              # độ trễ scrape so với nhãn mốc
        m["quote_checkin_lag_days"] = (m["checkin_dt"] - snap).dt.days
        
        # --- Q10: giá ngoài fence IQR (một mốc nên tính thẳng). IQR = 0 thì không cờ ---
        k = qa_cfg.get("iqr_multiplier", 1.5)
        q1, q3 = m["price_num"].quantile([0.25, 0.75])
        low, high = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
        m["flag_q10_outlier_iqr"] = (q3 > q1) & ((m["price_num"] < low) | (m["price_num"] > high))

        # --- K1-06: quote không khớp chuyến ngắn ---
        quote_price = pd.to_numeric(text["price_quote_price_per_night"], errors="coerce")
        m["flag_k1_quote_mismatch"] = (m["checkin_dt"].isna() | m["checkout_dt"].isna() | ((m["price_num"] - quote_price).abs() > 0.005))
        m["exclude_kpi1"] = (m["flag_q08_orphan"] | m["flag_k1_price_missing"]
                             | m["flag_q03_parse_error"] | m["flag_q03_domain_error"]
                             | m["flag_q06_conflict"] | m["flag_q06_extra_copy"])           # KHÔNG loại giá ngoại lai
    else:
        # --- KPI 2: tiện nghi ---
        r = pd.DataFrame(text["amenities"].map(read_amenities).tolist(), index=m.index,
                         columns=["status", "valid", "has_wifi", "has_kitchen", "has_pocket_wifi"])
        m["amenities_parse_status"] = r["status"]                                           # ok / missing / invalid
        m["valid_amenities"] = r["valid"].map(lambda x: json.dumps(x, ensure_ascii=False) if x is not None else pd.NA)
        m["flag_k2_amenities_missing"] = r["status"] == "missing"
        m["flag_k2_invalid_json"] = r["status"] == "invalid"
        for c in ["has_wifi", "has_kitchen", "has_pocket_wifi"]:
            m[c] = r[c].astype("boolean")                                                   # True / False / NA
        m["has_both"] = m["has_wifi"] & m["has_kitchen"]
        m["has_both_status"] = np.select([m["has_both"].isna(), m["has_both"].fillna(False).astype(bool)], ["unknown", "yes"], default="no")
        m["pocket_wifi_policy"] = POCKET_WIFI_POLICY
        # amenities thiếu có has_both = NA nên tự nằm ngoài mẫu số D; '[]' hợp lệ, vẫn ở D
        m["exclude_kpi2"] = (m["flag_q08_orphan"] | m["flag_k2_invalid_json"]
                             | m["flag_q06_conflict"] | m["flag_q06_extra_copy"])
    return m


def standardization_audit(m: pd.DataFrame, kpi: str, run_id: str) -> pd.DataFrame:
    """Nhật ký chuẩn hóa: mỗi ô có giá trị gốc bị đổi (hoặc thành NA) một dòng, kèm loại thay đổi và lý do."""
    pairs = [("room_type", "room_type_clean"), ("neighbourhood_group_cleansed", "borough_clean")]
    pairs += [("price", "price_num")] if kpi == "kpi1" else [("amenities", "valid_amenities")]
    out = []
    for raw, new in pairs:
        r, n = m[raw].fillna(""), m[new]
        blank = r.str.strip().str.casefold().isin(NA_TOKENS)                  # ô rỗng, whitespace hoặc token NA
        if raw == "price":
            why = m["price_status"]                                           # parse_error / nonfinite / nonpositive
        elif raw == "amenities":
            why = m["amenities_parse_status"]                                 # invalid
        else:
            why = pd.Series("not_in_domain", index=m.index)
        changed = n.astype("string").fillna("") != r                          # giá trị mới khác gốc (bỏ $ và dấu phẩy, sửa casing...)
        keep = blank | n.isna() | (changed & (raw != "amenities"))            # amenities hợp lệ không ghi từng ô
        kind = np.select([blank, n.isna()], ["missing_to_NA", "invalid_to_NA"], default="standardized")
        reason = np.where(blank, np.where(r == "", "blank", np.where(r.str.strip() == "", "whitespace", "na_token")),
                          np.where(n.isna(), why, "strip_symbols_or_casing"))
        out.append(pd.DataFrame({"kpi": kpi, "snapshot": m["snapshot"], "id": m["id"], "column": raw, "raw_value": r,
                                 "new_value": n, "change_type": kind, "reason": reason, "run_id": run_id})[keep])
    return pd.concat(out, ignore_index=True)


# -----------KHỐI 5: BÁO CÁO QA---------
def qa_report(m: pd.DataFrame, kpi: str, cfg: dict, run_id: str) -> pd.DataFrame:
    """Mỗi (mốc, quy tắc) một dòng theo QA_COLS, cộng một dòng FINAL áp mọi quy tắc loại."""
    root = Path(cfg.get("interim_dir", "data/interim"))
    min_coverage = cfg.get("qa", {}).get("min_coverage_pct", 80)
    excl = "exclude_" + kpi
    if kpi == "kpi1":
        value, unit, valid = (lambda x: x["price_num"].median()), "USD/đêm", "price_num"
    else:
        value, unit, valid = (lambda x: 100 * x["has_both"].sum() / x["has_both"].notna().sum() if x["has_both"].notna().any() else np.nan), "pp", "has_both"
    rows = []
    for snap, d in m.groupby("snapshot"):
        path = root / snap / "listings_filtered.csv.gz"
        base = dict(kpi=kpi, snapshot=snap, dataset="listings", group_key="ALL", observation_unit="listing_id", unit=unit,
                    run_id=run_id, rule_version=RULE_VERSION, decision_ref="PENDING",
                    source_path=str(path), source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        before = value(d)
        eligible = int((~d[excl] & d[valid].notna()).sum())          # còn đủ điều kiện sau MỌI quy tắc loại
        for rule_id, col, cond, reason, action, exclude in RULES + [("FINAL", excl, "áp mọi quy tắc loại theo thứ tự", "KPI cuối", "—", True)]:
            if col not in d.columns:
                continue                                             # quy tắc của KPI kia
            flag = d[col]
            kept = d[~flag] if exclude else d                        # quy tắc chỉ FLAG thì KPI không đổi
            after = value(kept)
            notes = ""
            if rule_id == "FINAL" and 100 * eligible / len(d) < min_coverage:
                notes = f"coverage_warning: coverage < {min_coverage}%"
            if rule_id == "Q04" and d["scrape_lag_days"].notna().any():
                notes = f"scrape_lag_days {int(d['scrape_lag_days'].min())}..{int(d['scrape_lag_days'].max())} (trễ hợp lệ, không cờ)"
            if rule_id == "K1-06":
                notes = f"{int((d['discount_amount'].fillna(0) != 0).sum())} quote có discount_amount khác 0"
            if rule_id == "Q10":                                     # sensitivity: KPI chính vẫn giữ giá ngoại lai
                notes = f"sensitivity: {unit} khi bỏ {int(flag.sum())} hàng bị cờ = {value(d[~flag]):.2f}"
            rows.append({**base, "rule_id": rule_id, "condition": cond, "reason": reason, "action": action,
                         "affected_rows": int(flag.sum()), "observations_before": len(d), "observations_after": len(kept),
                         "n_eligible": eligible, "coverage": 100 * eligible / len(d),
                         "kpi_before": before, "kpi_after": after, "delta": after - before,
                         "before_status": "ok" if pd.notna(before) else "not_computable",
                         "after_status": "ok" if pd.notna(after) else "not_computable", "notes": notes})
    return pd.DataFrame(rows, columns=QA_COLS)


# ── KHỐI 6: ĐIỀU PHỐI ──────────────────────────
def run(config_path: str) -> int:
    """Mỗi KPI chạy riêng: KPI nào thiếu file mốc thì báo lỗi và dừng KPI đó, KPI còn lại vẫn chạy.
    Vấn đề dữ liệu không làm mã thoát khác 0; thiếu file hoặc lỗi chương trình thì trả 1."""
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    started = datetime.now()
    run_id = started.strftime("%Y%m%d_%H%M%S")
    snaps = [str(s) for s in cfg["snapshots"]]
    qa_cfg = cfg.get("qa", {})
    kpi1_snapshot = str(qa_cfg.get("kpi1_snapshot", "2026-06-14"))       # yaml đọc 2026-06-14 thành kiểu ngày nên ép về chuỗi
    root = Path(cfg.get("interim_dir", "data/interim"))
    out_dir = Path(cfg.get("processed_dir", "data/processed"))
    qa_dir = Path(cfg.get("reports_dir", "reports")) / "qa"
    out_dir.mkdir(parents=True, exist_ok=True)
    qa_dir.mkdir(parents=True, exist_ok=True)

    code, status, reports, audits = 0, {}, [], []
    for kpi, kpi_snaps in [("kpi1", [kpi1_snapshot]), ("kpi2", snaps)]:
        try:
            m = build_manifest(load_interim(cfg, "listings", kpi_snaps), kpi, qa_cfg)
            m.to_csv(out_dir / f"manifest_{kpi}.csv", index=False, encoding="utf-8-sig")
            reports.append(qa_report(m, kpi, cfg, run_id))
            audits.append(standardization_audit(m, kpi, run_id))
            status[kpi] = "ok"
        except Exception:
            log.exception("%s thất bại", kpi)
            status[kpi], code = "failed", 1
    if reports:
        report = pd.concat(reports, ignore_index=True)
        report.to_csv(qa_dir / "qa_tv1.csv", index=False, encoding="utf-8-sig")
        pd.concat(audits, ignore_index=True).to_csv(qa_dir / "standardization_audit.csv", index=False, encoding="utf-8-sig")
        for _, r in report[report["rule_id"] == "FINAL"].iterrows():
            log.info("%s %s: %d/%d dòng đủ điều kiện (%.1f%%), KPI = %.2f %s",
                     r["kpi"], r["snapshot"], r["n_eligible"], r["observations_before"], r["coverage"], r["kpi_after"], r["unit"])
    meta = {"run_id": run_id, "started_at": started.isoformat(timespec="seconds"),
            "finished_at": datetime.now().isoformat(timespec="seconds"), "status": status,
            "rule_version": RULE_VERSION, "map_version": MAP_VERSION, "pocket_wifi_policy": POCKET_WIFI_POLICY,
            "price_source": PRICE_SOURCE, "kpi1_snapshot": kpi1_snapshot, "snapshots": snaps, "qa_config": qa_cfg,
            "sources": [{"snapshot": s, "path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                        for s in sorted({kpi1_snapshot, *snaps}) for p in [root / s / "listings_filtered.csv.gz"] if p.exists()],
            "python": sys.version.split()[0], "pandas": pd.__version__}
    (qa_dir / "pipeline_metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return code


# ── KHỐI 7: ĐIỂM VÀO ───────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    sys.exit(run(ap.parse_args().config))
