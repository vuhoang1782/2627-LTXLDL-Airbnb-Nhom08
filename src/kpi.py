"""Tính 7 KPI từ dữ liệu đã QA (data/processed). Không làm sạch lại: chỉ dùng cờ do qa.py tạo.

Mỗi KPI: tên -> mục tiêu -> công thức -> đơn vị (xem kpi_definitions.csv). Mốc dùng cho từng KPI nằm trong config
(kpi.*_snapshot_index), không ghi cứng ngày. Quy ước chung: mẫu số 0 -> NaN (không bao giờ ghi 0%).
Cuối cùng ghi giá trị KPI 'trước QA / sau QA' vào reports/qa_report.csv.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils import ensure_dir, folder, get_logger, read_clean, snapshot_of, table_file

log = get_logger("kpi")


def pct1(n, d):
    """Phần trăm n/d cho số đơn; d = 0 -> NaN."""
    return n / d * 100 if d > 0 else np.nan


def pct(n, d):
    """Phần trăm n/d cho cả cột; d = 0 -> NaN."""
    return n / d.where(d > 0) * 100


def clean(cfg, snap, name):
    return read_clean(table_file(cfg, "processed", snap, f"{name}_clean"))


def save(cfg, df, name):
    path = ensure_dir(folder(cfg, "processed")) / name
    df.to_csv(path, index=False)
    log.info("-> %s (%d dòng)", path.name, len(df))


def group_base(L):
    """Listing dùng được cho nhóm quận x loại phòng: một dòng/listing và có đủ hai nhãn."""
    return L[L["analysis_row"] & L["borough_ok"] & L["room_type_ok"]]


# ---------------------------------------------------------------- KPI 1
def kpi1(cfg):
    snap = snapshot_of(cfg, "kpi1_snapshot_index")
    base = group_base(clean(cfg, snap, "listings"))
    g = base.groupby(["borough", "room_type_std"])["price_num"]
    out = pd.DataFrame({"n_total": g.size(), "n_valid": g.count(), "median_price": g.median()}).reset_index()
    out = out.rename(columns={"room_type_std": "room_type"})
    out["coverage_pct"] = pct(out["n_valid"], out["n_total"])
    out.insert(0, "snapshot", snap)
    out["currency"] = cfg["currency"]
    return out, [("QA04", snap, "KPI1 giá trung vị toàn mẫu", base["price_parsed"].median(), base["price_num"].median())]


# ---------------------------------------------------------------- KPI 2
def kpi2(cfg):
    rows, impact = [], []
    for snap in cfg["snapshots"]:
        base = group_base(clean(cfg, snap, "listings"))
        d = base[base["amenities_status"] == "ok"]                          # D: amenities hợp lệ (kể cả [])
        both = d[(d["has_wifi"] == "T") & (d["has_kitchen"] == "T")]         # B: có cả Wi-Fi và Kitchen
        key = ["borough", "room_type_std"]
        t = pd.DataFrame({"n_total": base.groupby(key).size(), "n_valid": d.groupby(key).size(),
                          "n_both": both.groupby(key).size()}).fillna(0).astype(int).reset_index()
        t["kpi2_pct"], t["coverage_pct"] = pct(t["n_both"], t["n_valid"]), pct(t["n_valid"], t["n_total"])
        rows.append(t.assign(snapshot=snap))
        impact.append(("QA05", snap, "KPI2 toàn mẫu", pct1(len(both), len(base)), pct1(len(both), len(d))))
    out = pd.concat(rows, ignore_index=True).rename(columns={"room_type_std": "room_type"})
    return out[["snapshot", "borough", "room_type", "n_total", "n_valid", "n_both", "kpi2_pct", "coverage_pct"]], impact


# ---------------------------------------------------------------- KPI 3
def kpi3(cfg):
    k, snap = cfg["kpi"], snapshot_of(cfg, "kpi3_snapshot_index")
    L = clean(cfg, snap, "listings")
    L = L[L["analysis_row"]]                                                 # mỗi listing đúng một dòng
    C = clean(cfg, snap, "calendar")
    C = C[C["kpi3_day_eligible"]].assign(day=lambda x: pd.to_datetime(x["date_iso"]))
    days = pd.date_range(pd.Timestamp(snap) + pd.Timedelta(days=1), periods=k["window_days"])

    def grid(col):        # bảng listing x ngày; ngày thiếu trong lịch -> NaN (= chưa xác định)
        return C.pivot(index="listing_id", columns="day", values=col).reindex(index=L["id"], columns=days).to_numpy(dtype=object)

    avail, limits = grid("available_state"), grid("constraints_state")
    n_in = k["window_days"] - k["stay_nights"] + 1                           # số ngày nhận phòng tiềm năng (88)
    three = np.stack([avail[:, i:i + n_in] for i in range(k["stay_nights"])])  # ngày s, s+1, s+2
    a_T, a_F = (three == "T").all(axis=0), (three == "F").any(axis=0)       # điều kiện A: cả 3 đêm mở / có đêm chắc chắn đóng
    b = limits[:, :n_in]                                                     # điều kiện B: chỉ xét giới hạn tại ngày nhận phòng s
    chain_T, chain_F = a_T & (b == "T"), a_F | (b == "F")
    state = np.where(chain_T.any(axis=1), "T", np.where(chain_F.all(axis=1), "F", "U"))   # T: có chuỗi T; F: mọi chuỗi F; còn lại U
    lv = L[["id", "borough", "room_type_std", "borough_ok", "room_type_ok"]].assign(state=state)

    def summary(df, scope, borough="", room=""):
        t, f, u = ((df["state"] == s).sum() for s in "TFU")
        return {"scope": scope, "borough": borough, "room_type": room, "T": t, "F": f, "U": u, "kpi3_pct": pct1(t, t + f),
                "coverage_pct": pct1(t + f, t + f + u), "lower_pct": pct1(t, t + f + u), "upper_pct": pct1(t + u, t + f + u)}

    rows = [summary(lv, "ALL")]
    for (bo, rm), g in lv[lv["borough_ok"] & lv["room_type_ok"]].groupby(["borough", "room_type_std"]):
        rows.append(summary(g, "borough_room", bo, rm))
    out = pd.DataFrame(rows)
    out.insert(0, "snapshot", snap)
    listing_level = lv.rename(columns={"id": "listing_id", "room_type_std": "room_type"})[["listing_id", "borough", "room_type", "state"]]
    return out, listing_level, [("QA08", snap, "KPI3 toàn mẫu", rows[0]["lower_pct"], rows[0]["kpi3_pct"])]


# ---------------------------------------------------------------- KPI 4
def kpi4(cfg):
    snaps, min_n = cfg["snapshots"], cfg["kpi"]["min_price_count"]
    parts, impact = [], []
    for s in snaps:
        L = clean(cfg, s, "listings")
        base = L[L["analysis_row"] & L["borough_ok"] & L["neigh_ok"] & L["room_type_ok"]]
        g = base.groupby(["borough", "neighbourhood"])["price_num"]
        parts.append(pd.DataFrame({"n_valid": g.count(), "median_price": g.median()}).assign(snapshot=s).reset_index())
        impact.append(("QA04", s, "KPI4 giá trung vị toàn mẫu", base["price_parsed"].median(), base["price_num"].median()))
    long = pd.concat(parts, ignore_index=True)
    key = ["borough", "neighbourhood"]
    med = long.pivot(index=key, columns="snapshot", values="median_price").reindex(columns=snaps)
    cnt = long.pivot(index=key, columns="snapshot", values="n_valid").reindex(columns=snaps).fillna(0)
    rows = []
    for i, s in enumerate(snaps):
        o = pd.DataFrame({"snapshot": s, "n_valid": cnt[s].astype(int), "median_price": med[s]})
        o["delta_prev"] = o["change_prev_pct"] = o["change_base_pct"] = np.nan
        if i:
            ok_prev = (cnt[s] >= min_n) & (cnt[snaps[i - 1]] >= min_n)       # chỉ so sánh khi cả hai mốc có >= 10 giá hợp lệ
            ok_base = (cnt[s] >= min_n) & (cnt[snaps[0]] >= min_n)
            o["delta_prev"] = (med[s] - med[snaps[i - 1]]).where(ok_prev)
            o["change_prev_pct"] = ((med[s] / med[snaps[i - 1]] - 1) * 100).where(ok_prev)
            o["change_base_pct"] = ((med[s] / med[snaps[0]] - 1) * 100).where(ok_base)
        rows.append(o.reset_index())
    out = pd.concat(rows, ignore_index=True)
    out["currency"] = cfg["currency"]
    return out, impact


# ---------------------------------------------------------------- KPI 5
def kpi5(cfg):
    snaps, rows, impact = cfg["snapshots"], [], []
    for s in snaps:
        a = clean(cfg, s, "listings")
        a = a[a["analysis_row"]]                                             # đơn vị đếm là listing, không phải host
        def summary(df, scope, borough=""):
            t, f, u = ((df["superhost_state"] == x).sum() for x in "TFU")
            return {"snapshot": s, "scope": scope, "borough": borough, "T": t, "F": f, "U": u,
                    "kpi5_pct": pct1(t, t + f), "coverage_pct": pct1(t + f, t + f + u)}
        overall = summary(a, "ALL")
        rows.append(overall)
        rows += [summary(g, "borough", b) for b, g in a[a["borough_ok"]].groupby("borough")]
        impact.append(("QA07", s, "KPI5 toàn mẫu", pct1(overall["T"], len(a)), overall["kpi5_pct"]))   # trước QA: U tính như F
    df = pd.DataFrame(rows)
    p = df.pivot(index=["scope", "borough"], columns="snapshot", values="kpi5_pct").reindex(columns=snaps)
    parts = []
    for i, s in enumerate(snaps):
        o = df[df["snapshot"] == s].set_index(["scope", "borough"])
        o["delta_prev_pp"] = o["kpi5_pct"] - p[snaps[i - 1]] if i else np.nan          # điểm phần trăm, không phải % tương đối
        o["delta_base_pp"] = o["kpi5_pct"] - p[snaps[0]] if i else np.nan
        parts.append(o.reset_index())
    return pd.concat(parts, ignore_index=True), impact


# ---------------------------------------------------------------- KPI 6 và 7 (dùng kết quả LLM)
def kpi6_7(cfg):
    path = folder(cfg, "processed") / "llm_clean.csv.gz"
    if not path.exists():
        raise FileNotFoundError("chưa có llm_clean.csv.gz (chạy bước llm và qa_post)")
    M = read_clean(path)
    rooms, aspects = cfg["kpi"]["llm_room_types"], list(cfg["llm"]["aspects"])
    reviews_after = M[M["kpi6_eligible"]]
    # Trước QA10: ghép prediction gốc với cùng mẫu/loại phòng, chưa áp cờ QA10.
    predictions_before = pd.read_csv(folder(cfg, "processed") / "llm_predictions.csv.gz",
                                     dtype=str, keep_default_na=False)
    predictions_before = predictions_before.merge(M[["review_id", "room_type_std"]],
                                                   on="review_id", how="inner", validate="many_to_one")
    # B: lượt có chê; D: lượt có khen hoặc chê. *_total dùng cho QA report.
    B_before_total = D_before_total = 0
    B_after_total = D_after_total = 0
    k6, k7 = [], []
    for room in rooms:
        group_before = predictions_before[predictions_before["room_type_std"] == room]
        group_after = reviews_after[reviews_after["room_type_std"] == room]
        n_after = len(group_after)
        n_negative_after = int(group_after["sentiment"].eq("negative").sum())
        k6.append({"room_type": room, "total_reviews_in_group": n_after,
                   "reviews_negative_sentiment": n_negative_after,
                   "negative_sentiment_pct_of_group": pct1(n_negative_after, n_after)})
        for aspect in aspects:
            # Đếm B/D trước QA10, chưa loại prediction theo các cờ hợp lệ.
            positive_before = pd.to_numeric(group_before[f"{aspect}_positive"], errors="coerce").eq(1)
            negative_before = pd.to_numeric(group_before[f"{aspect}_negative"], errors="coerce").eq(1)
            B_before = int(negative_before.sum())
            D_before = int((positive_before | negative_before).sum())
            B_before_total += B_before
            D_before_total += D_before
            # Sau QA10: review và cặp khía cạnh đều phải hợp lệ; OR tránh đếm đôi.
            aspect_after = group_after[group_after[f"{aspect}_ok"]]
            positive_after = pd.to_numeric(aspect_after[f"{aspect}_positive"], errors="coerce").eq(1)
            negative_after = pd.to_numeric(aspect_after[f"{aspect}_negative"], errors="coerce").eq(1)
            B_after = int(negative_after.sum())
            D_after = int((positive_after | negative_after).sum())
            B_after_total += B_after
            D_after_total += D_after
            k7.append({"room_type": room, "aspect": aspect, "total_reviews_in_group": n_after,
                       "reviews_evaluating_aspect": D_after, "reviews_negative_on_aspect": B_after,
                       "negative_pct_among_aspect_reviews": pct1(B_after, D_after)})
    k6, k7 = pd.DataFrame(k6), pd.DataFrame(k7)
    snap = snapshot_of(cfg, "llm_snapshot_index")
    # KPI 6 before6 chưa lọc cờ kpi6_eligible.
    in_rooms = M[M["room_type_std"].isin(rooms)]
    before6 = pct1(int((in_rooms["sentiment"] == "negative").sum()), len(in_rooms))
    after6 = pct1(k6["reviews_negative_sentiment"].sum(), k6["total_reviews_in_group"].sum())
    # KPI 7 dùng cùng công thức B/D với số đếm trước/sau độc lập.
    before7 = pct1(B_before_total, D_before_total)
    after7 = pct1(B_after_total, D_after_total)
    return k6, k7, [("QA10", snap, "KPI6 toàn mẫu", before6, after6), ("QA10", snap, "KPI7 gộp 5 aspect", before7, after7)]


# ---------------------------------------------------------------- tài liệu KPI và tác động QA
def definitions(cfg):
    cur, sn = cfg["currency"], cfg["snapshots"]
    s = lambda key: sn[cfg["kpi"][key]]
    rows = [
        (1, "Giá trung vị niêm yết", "Mức giá điển hình theo quận x loại phòng, tư vấn ngân sách", "Median(giá hợp lệ > 0); coverage = n_valid/n_total", f"{cur}/đêm", s("kpi1_snapshot_index")),
        (2, "Tỷ lệ listing khai báo Wi-Fi và Kitchen", "Sàng lọc chỗ ở có Internet và bếp", "B/D x 100 (D: amenities hợp lệ; B: có cả Wi-Fi và Kitchen)", "%", "cả 4 mốc"),
        (3, "Tỷ lệ listing đáp ứng 3 đêm liên tiếp", "Khả năng cung cấp gói 3 đêm trong 90 đêm", "T/(T+F) x 100; U không vào mẫu số; kèm coverage, lower, upper", "%", s("kpi3_snapshot_index")),
        (4, "Biến động giá trung vị theo khu phố", "Theo dõi thay đổi ngân sách theo khu phố", "delta = M_t - M_(t-1); change = (M_t/M_(t-1) - 1) x 100; chỉ so khi cả hai mốc có >= 10 giá", f"{cur}/đêm và %", "cả 4 mốc"),
        (5, "Biến động tỷ lệ listing thuộc Superhost", "Tìm tín hiệu uy tín của chủ nhà", "T/(T+F) x 100; chênh lệch tính bằng điểm phần trăm", "% và pp", "cả 4 mốc"),
        (6, "Tỷ lệ review tiêu cực theo loại phòng (LLM)", "Nhận diện phân khúc cần kiểm tra kỹ", "negative / (positive+mixed+negative) x 100", "%", s("llm_snapshot_index")),
        (7, "Tỷ lệ phàn nàn theo 5 yếu tố (LLM)", "Yếu tố nào bị chê nhiều nhất trong review có đánh giá yếu tố đó", "|N| / |P ∪ N| x 100", "%", s("llm_snapshot_index")),
    ]
    return pd.DataFrame(rows, columns=["kpi_id", "ten", "muc_tieu", "cong_thuc", "don_vi", "mốc"]).assign(
        ben_lien_quan=cfg["kpi"].get("stakeholder", ""))


def write_impact(cfg, impacts):
    """Điền cột kpi / kpi_before / kpi_after vào reports/qa_report.csv (dòng của quy tắc và mốc tương ứng)."""
    path = folder(cfg, "reports") / "qa_report.csv"
    if not path.exists():
        return
    rep = pd.read_csv(path)
    rep = rep[~rep["note"].fillna("").str.endswith("[bản sao cho KPI khác]")].copy()   # chạy lại không bị nhân dòng
    rep["kpi"] = ""
    rep["kpi_before"] = rep["kpi_after"] = np.nan
    extra = []
    for rule, snap, name, before, after in impacts:
        idx = rep.index[(rep["rule"] == rule) & (rep["snapshot"] == snap)]
        if len(idx) == 0:
            continue
        i = idx[0]
        if rep.at[i, "kpi"] == "":
            rep.loc[i, ["kpi", "kpi_before", "kpi_after"]] = [name, before, after]
        else:                                                                 # một dòng QA ảnh hưởng 2 KPI: thêm dòng bản sao
            row = rep.loc[i].copy()
            row["kpi"], row["kpi_before"], row["kpi_after"] = name, before, after
            row["note"] = f"{row['note'] if isinstance(row['note'], str) else ''} [bản sao cho KPI khác]"
            extra.append(row)
    pd.concat([rep, pd.DataFrame(extra)], ignore_index=True).to_csv(path, index=False)


def run(cfg):
    impacts = []
    jobs = [("KPI 1", "kpi_01_median_price.csv", kpi1), ("KPI 2", "kpi_02_wifi_kitchen.csv", kpi2),
            ("KPI 4", "kpi_04_price_change.csv", kpi4), ("KPI 5", "kpi_05_superhost.csv", kpi5)]
    for label, fname, fn in jobs:
        try:
            df, imp = fn(cfg)
            save(cfg, df, fname)
            impacts += imp
        except (KeyError, FileNotFoundError) as e:
            log.error("%s bị chặn: thiếu %s", label, e)
    try:
        df, listing_level, imp = kpi3(cfg)
        save(cfg, df, "kpi_03_three_night.csv")
        save(cfg, listing_level, "kpi_03_listing_level.csv")
        impacts += imp
    except (KeyError, FileNotFoundError, ValueError) as e:
        log.error("KPI 3 bị chặn: %s", e)
    try:
        k6, k7, imp = kpi6_7(cfg)
        save(cfg, k6, "kpi_06_negative_sentiment.csv")
        save(cfg, k7, "kpi_07_aspect_complaint.csv")
        impacts += imp
    except (KeyError, FileNotFoundError) as e:
        log.error("KPI 6/7 bị chặn: %s", e)
    save(cfg, definitions(cfg), "kpi_definitions.csv")
    write_impact(cfg, impacts)
