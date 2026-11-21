"""Tính 7 KPI từ dữ liệu đã QA (data/processed). Không làm sạch lại: chỉ dùng cờ do qa.py tạo.

Mỗi KPI: tên -> mục tiêu -> công thức -> đơn vị. Mốc dùng cho từng KPI nằm trong config
(kpi.*_snapshot_index), không ghi cứng ngày. Quy ước chung: mẫu số 0 -> NaN (không bao giờ ghi 0%).
Thiếu đầu vào thì dừng ngay (không bỏ qua KPI lặng lẽ). Tác động của QA đã ghi ở reports/qa_report.csv.
Chạy:  python -m src.kpi --config X.yaml
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils import PROC, clean_file, cli, ensure_dir, get_logger, pct, pct1, read_clean, snapshot_of

log = get_logger("kpi")


def group_base(L):
    """Listing dùng được cho nhóm quận x loại phòng: có đủ hai nhãn."""
    return L[L["borough_ok"] & L["room_type_ok"]]


# ---------------------------------------------------------------- KPI 1
def kpi1(cfg):
    snap = snapshot_of(cfg, "kpi1_snapshot_index")
    base = group_base(read_clean(clean_file(snap, "listings")))
    g = base.groupby(["borough", "room_type_std"])["price_num"]
    out = pd.DataFrame({"n_total": g.size(), "n_valid": g.count(), "median_price": g.median()}).reset_index()
    out = out.rename(columns={"room_type_std": "room_type"})
    out["coverage_pct"] = pct(out["n_valid"], out["n_total"])
    out.insert(0, "snapshot", snap)
    out["currency"] = cfg["currency"]
    return out


# ---------------------------------------------------------------- KPI 2
def kpi2(cfg):
    rows = []
    for snap in cfg["snapshots"]:
        base = group_base(read_clean(clean_file(snap, "listings")))
        d = base[base["has_wifi"].notna()]                                  # D: amenities hợp lệ (kể cả [])
        both = d[d["has_wifi"] & d["has_kitchen"]]                          # B: có cả Wi-Fi và Kitchen
        key = ["borough", "room_type_std"]
        t = pd.DataFrame({"n_total": base.groupby(key).size(), "n_valid": d.groupby(key).size(),
                          "n_both": both.groupby(key).size()}).fillna(0).astype(int).reset_index()
        t["kpi2_pct"], t["coverage_pct"] = pct(t["n_both"], t["n_valid"]), pct(t["n_valid"], t["n_total"])
        rows.append(t.assign(snapshot=snap))
    out = pd.concat(rows, ignore_index=True).rename(columns={"room_type_std": "room_type"})
    return out[["snapshot", "borough", "room_type", "n_total", "n_valid", "n_both", "kpi2_pct", "coverage_pct"]]


# ---------------------------------------------------------------- KPI 3
def kpi3(cfg):
    k, snap = cfg["kpi"], snapshot_of(cfg, "kpi3_snapshot_index")
    L = read_clean(clean_file(snap, "listings"))
    C = read_clean(clean_file(snap, "calendar"))
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
    return out


# ---------------------------------------------------------------- KPI 4
def kpi4(cfg):
    snaps, min_n = cfg["snapshots"], cfg["kpi"]["min_price_count"]
    parts = []
    for s in snaps:
        L = read_clean(clean_file(s, "listings"))
        base = L[L["borough_ok"] & L["neigh_ok"] & L["room_type_ok"]]
        g = base.groupby(["borough", "neighbourhood"])["price_num"]
        parts.append(pd.DataFrame({"n_valid": g.count(), "median_price": g.median()}).assign(snapshot=s).reset_index())
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
    return out


# ---------------------------------------------------------------- KPI 5
def kpi5(cfg):
    snaps, rows = cfg["snapshots"], []
    for s in snaps:
        a = read_clean(clean_file(s, "listings"))                            # đơn vị đếm là listing, không phải host

        def summary(df, scope, borough=""):
            sh = df["is_superhost"]
            t, f, u = sh.eq(True).sum(), sh.eq(False).sum(), sh.isna().sum()
            return {"snapshot": s, "scope": scope, "borough": borough, "T": t, "F": f, "U": u,
                    "kpi5_pct": pct1(t, t + f), "coverage_pct": pct1(t + f, t + f + u)}
        rows.append(summary(a, "ALL"))
        rows += [summary(g, "borough", b) for b, g in a[a["borough_ok"]].groupby("borough")]
    df = pd.DataFrame(rows)
    p = df.pivot(index=["scope", "borough"], columns="snapshot", values="kpi5_pct").reindex(columns=snaps)
    parts = []
    for i, s in enumerate(snaps):
        o = df[df["snapshot"] == s].set_index(["scope", "borough"])
        o["delta_prev_pp"] = o["kpi5_pct"] - p[snaps[i - 1]] if i else np.nan          # điểm phần trăm, không phải % tương đối
        o["delta_base_pp"] = o["kpi5_pct"] - p[snaps[0]] if i else np.nan
        parts.append(o.reset_index())
    return pd.concat(parts, ignore_index=True)


# ---------------------------------------------------------------- KPI 6 và 7 (dùng kết quả LLM)
def kpi6_7(cfg):
    path = PROC / "llm_clean.csv.gz"
    if not path.exists():
        raise SystemExit("chưa có llm_clean.csv.gz (chạy bước llm rồi qa --post)")
    ok = read_clean(path)
    ok = ok[ok["kpi6_eligible"]]
    rooms, aspects = cfg["kpi"]["llm_room_types"], list(cfg["llm"]["aspects"])
    k6, k7 = [], []
    for room in rooms:
        g = ok[ok["room_type_std"] == room]
        n, n_neg = len(g), int(g["sentiment"].eq("negative").sum())
        k6.append({"room_type": room, "total_reviews_in_group": n, "reviews_negative_sentiment": n_neg,
                   "negative_sentiment_pct_of_group": pct1(n_neg, n)})
        for aspect in aspects:
            # B: lượt có chê; D: lượt có khen hoặc chê (OR tránh đếm đôi)
            pos = pd.to_numeric(g[f"{aspect}_positive"], errors="coerce").eq(1)
            neg = pd.to_numeric(g[f"{aspect}_negative"], errors="coerce").eq(1)
            B, D = int(neg.sum()), int((pos | neg).sum())
            k7.append({"room_type": room, "aspect": aspect, "total_reviews_in_group": n,
                       "reviews_evaluating_aspect": D, "reviews_negative_on_aspect": B,
                       "negative_pct_among_aspect_reviews": pct1(B, D)})
    return pd.DataFrame(k6), pd.DataFrame(k7)


def main(cfg):
    k6, k7 = kpi6_7(cfg)
    outs = {"kpi_01_median_price.csv": kpi1(cfg), "kpi_02_wifi_kitchen.csv": kpi2(cfg), "kpi_03_three_night.csv": kpi3(cfg),
            "kpi_04_price_change.csv": kpi4(cfg), "kpi_05_superhost.csv": kpi5(cfg),
            "kpi_06_negative_sentiment.csv": k6, "kpi_07_aspect_complaint.csv": k7}
    for name, df in outs.items():
        df.to_csv(ensure_dir(PROC) / name, index=False)
        log.info("-> %s (%d dòng)", name, len(df))


if __name__ == "__main__":
    cli(main)
