"""Hình tự sinh vào figures/ bằng plotnine: MỖI KPI MỘT HÌNH (KPI 4 thêm bản đồ giá theo khu phố), chỉ PNG, đọc từ kết quả KPI ở data/processed.

Bản đồ dùng ranh giới visualisations/neighbourhoods.geojson (tự tải vào data/raw/<mốc>/ nếu chưa có); không tải được thì bỏ qua bản đồ.
Loại biểu đồ: chart (cột/đường), heatmap (bảng nhiệt), dumbbell (so hai mốc), choropleth (bản đồ tô màu).
Thiếu tệp KPI hoặc hình không có số liệu thì dừng ngay với thông báo rõ.
Chạy:  python -m src.viz --config X.yaml
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np
import pandas as pd
from plotnine import (aes, coord_fixed, element_blank, element_text, geom_col, geom_line, geom_point, geom_polygon,
                      geom_segment, geom_text, geom_tile, ggplot, labs, position_dodge, scale_color_identity,
                      scale_color_manual, scale_fill_gradient, scale_fill_manual, scale_x_continuous,
                      scale_y_continuous, theme, theme_minimal, theme_void)

from src.utils import FIGURES, PROC, RAW, cli, ensure_dir, get_logger

log = get_logger("viz")
PALETTE = ["#2b4f72", "#e08a1e", "#3b8ea5", "#c75146", "#7a9e7e", "#8e6c8a"]      # bảng màu chung cho mọi hình


def pal(n):
    return [PALETTE[i % len(PALETTE)] for i in range(n)]


def order(s):
    """Các giá trị (chuỗi) theo thứ tự xuất hiện: dùng làm thứ tự trục rời rạc."""
    return list(dict.fromkeys(s.astype(str)))


def base(w, h):
    """Giao diện chung: nền sáng, bỏ lưới phụ, tiêu đề đậm."""
    return theme_minimal() + theme(figure_size=(w, h), plot_title=element_text(size=11, weight="bold"),
                                   panel_grid_minor=element_blank())


def need(ok, name):
    if not ok:
        raise SystemExit(f"{name}: không có số liệu để vẽ")


def fmt_pct(s):
    return s.map(lambda v: f"{v:.1f}%" if v == v else "–")                         # NaN -> "–"


def save(p, out, name):
    p.save(out / f"{name}.png", dpi=150, verbose=False)


# ---------------------------------------------------------------- cột / đường
def chart(out, df, kind, x, y, color, title, ylabel, name):
    """kind: 'bar' (cột) hoặc 'line' (đường). color = cột tách nhóm theo màu (None = một màu)."""
    d = df.dropna(subset=[y]).copy()
    need(not d.empty, name)
    d[x] = pd.Categorical(d[x].astype(str), categories=order(d[x]))
    d["lab"] = d[y].map(lambda v: f"{v:.1f}")
    m, lbl = {"x": x, "y": y}, {"title": title, "x": "", "y": ylabel}
    if color:
        d[color] = pd.Categorical(d[color].astype(str), categories=order(d[color]))
        m["color" if kind == "line" else "fill"] = color
        lbl["color" if kind == "line" else "fill"] = color
        if kind == "line":
            m["group"] = color
    if kind == "bar":
        dodge = position_dodge(width=0.8)
        p = (ggplot(d, aes(**m)) + geom_col(position=dodge, width=0.7, **({} if color else {"fill": PALETTE[0]}))
             + geom_text(aes(label="lab"), position=dodge, va="bottom", size=7)      # ghi giá trị trên đầu cột
             + scale_y_continuous(expand=(0, 0, 0.12, 0))
             + base(8, 4.5) + theme(axis_text_x=element_text(rotation=20, ha="right")))
        if color:
            p += scale_fill_manual(values=pal(len(d[color].cat.categories)))
    else:
        p = ggplot(d, aes(**m)) + geom_line() + geom_point(size=2.5) + base(8, 4.5)
        if color:
            p += scale_color_manual(values=pal(len(d[color].cat.categories)))
    save(p + labs(**lbl), out, name)


# ---------------------------------------------------------------- bảng nhiệt
def heatmap(out, values, text, title, label, name, high="#c75146"):
    """values: bảng số (hàng x cột) để tô màu; text: bảng chuỗi cùng cỡ để ghi trong ô (ô NaN ghi '–')."""
    z = values.to_numpy(float)
    need(not np.isnan(z).all(), name)
    lo, hi = np.nanmin(z), np.nanmax(z)
    rows = [(str(r), str(c), z[i, j], text.iat[i, j] if z[i, j] == z[i, j] else "–")
            for i, r in enumerate(values.index) for j, c in enumerate(values.columns)]
    d = pd.DataFrame(rows, columns=["row", "col", "v", "lab"])
    d["tc"] = np.where((d["v"] - lo) / ((hi - lo) or 1) > 0.6, "white", "black")      # chữ trắng trên ô đậm
    d["row"] = pd.Categorical(d["row"], categories=[str(r) for r in values.index][::-1])   # hàng đầu nằm trên cùng
    d["col"] = pd.Categorical(d["col"], categories=[str(c) for c in values.columns])
    p = (ggplot(d, aes("col", "row", fill="v")) + geom_tile(color="white")
         + geom_text(aes(label="lab", color="tc"), size=8) + scale_color_identity()
         + scale_fill_gradient(low="#f4f1ea", high=high, na_value="#eeeeee")
         + labs(title=title, x="", y="", fill=label) + base(1.7 * z.shape[1] + 3, 0.65 * z.shape[0] + 2)
         + theme(panel_grid_major=element_blank()))
    save(p, out, name)


# ---------------------------------------------------------------- so sánh hai mốc (quả tạ)
def dumbbell(out, df, y, a, b, la, lb, title, xlabel, name):
    """Mỗi hàng một khu vực: chấm xanh = giá trị cột a, chấm cam = cột b, nối bằng đoạn thẳng; ghi giá trị và mức thay đổi."""
    d = df.dropna(subset=[a, b]).sort_values(b).reset_index(drop=True)
    need(not d.empty, name)
    d["pos"] = np.arange(len(d))
    lo, hi = d[[a, b]].min().min(), d[[a, b]].max().max()
    d["xt"] = d[[a, b]].max(axis=1) + (hi - lo) * 0.01
    d["lab"] = [f"{r[b]:,.0f} ({r[b] - r[a]:+,.0f})" for _, r in d.iterrows()]
    pts = d.melt(id_vars=["pos"], value_vars=[a, b], var_name="mốc", value_name="giá")
    pts["mốc"] = pts["mốc"].map({a: la, b: lb})
    top = d.loc[[(d[b] - d[a]).idxmax()]].assign(note="tăng mạnh nhất", ypos=lambda t: t["pos"] + 0.45)
    p = (ggplot() + geom_segment(d, aes(x=a, xend=b, y="pos", yend="pos"), color="#9aa5b1")
         + geom_point(pts, aes(x="giá", y="pos", color="mốc"), size=3.5)
         + geom_text(d, aes(x="xt", y="pos", label="lab"), ha="left", size=7)
         + geom_text(top, aes(x=b, y="ypos", label="note"), color=PALETTE[3], size=8, fontweight="bold")
         + scale_color_manual(values={la: PALETTE[0], lb: PALETTE[1]})
         + scale_y_continuous(breaks=list(d["pos"]), labels=list(d[y]))
         + scale_x_continuous(limits=(lo * 0.9, hi * 1.2))
         + labs(title=title, x=xlabel, y="", color="") + base(8, 0.45 * len(d) + 2))
    save(p, out, name)


# ---------------------------------------------------------------- bản đồ từ geojson
def load_geojson(cfg):
    """Dùng tệp có sẵn ở data/raw/<mốc>/neighbourhoods.geojson; chưa có thì tải về cho mốc mới nhất. Lỗi thì trả None."""
    snaps = cfg["snapshots"]
    path = next((p for s in reversed(snaps) if (p := RAW / s / "neighbourhoods.geojson").exists()), None)
    if path is None:
        path = RAW / snaps[-1] / "neighbourhoods.geojson"
        url = f"{cfg.get('base_url', 'https://data.insideairbnb.com').rstrip('/')}/{cfg['data_root'].strip('/')}/{snaps[-1]}/visualisations/neighbourhoods.geojson"
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as r:
                data = r.read()
            json.loads(data)                                       # phải là JSON hợp lệ trước khi lưu
            ensure_dir(path.parent)
            path.write_bytes(data)
        except Exception as e:
            log.warning("Không tải được %s (%s) -> bỏ qua bản đồ", url, e)
            return None
    return json.loads(path.read_text(encoding="utf-8"))


def names(f):
    """(quận, khu phố) của một vùng. Phải khớp CẢ HAI: nhiều khu phố trùng tên ở các quận khác nhau."""
    p = f["properties"]
    return str(p.get("neighbourhood_group") or "").strip(), str(p.get("neighbourhood") or "").strip()


def rings(geometry):
    """Đường viền ngoài của mọi đa giác trong một vùng (Polygon hoặc MultiPolygon); bỏ qua lỗ."""
    polys = [geometry["coordinates"]] if geometry["type"] == "Polygon" else geometry["coordinates"]
    return [np.asarray(p[0])[:, :2] for p in polys]


def biggest(rs):
    """Đa giác lớn nhất (theo khung bao) của một vùng: nơi đặt nhãn, để vùng nhiều mảnh hay đảo không bị nhãn rơi vào khoảng trống."""
    return max(rs, key=lambda r: np.ptp(r[:, 0]) * np.ptp(r[:, 1]))


def choropleth(out, geo, key_of, values, title, label, name):
    """Tô màu từng vùng theo values = {khoá vùng: (giá trị, chú thích)}. Vùng không có giá trị: xám nhạt."""
    values = {k: v for k, v in values.items() if v[0] == v[0]}      # bỏ giá trị NaN
    need(bool(values), name)
    known = {key_of(f) for f in geo["features"]}
    if lost := [k for k in values if k not in known]:
        log.warning("%s: %d/%d tên không khớp với geojson (vd. %s)", name, len(lost), len(values), lost[:3])
    lo, hi = np.nanpercentile([v for v, _ in values.values()], [5, 95])     # cắt 5% hai đầu để vài giá trị cực đoan không làm nhạt bản đồ
    hi = hi if hi > lo else lo + 1
    rows, tags = [], []
    for i, f in enumerate(geo["features"]):
        key, rs = key_of(f), rings(f["geometry"])
        val = min(max(values[key][0], lo), hi) if key in values else np.nan
        for j, r in enumerate(rs):
            rows += [(px, py, f"{i}_{j}", val) for px, py in r]
        if key in values and len(values) <= 30:                              # ít vùng thì ghi tên
            a = biggest(rs)
            (cx, cy) = (a.min(axis=0) + a.max(axis=0)) / 2
            tags.append((cx, cy, key if isinstance(key, str) else key[1]))
    poly = pd.DataFrame(rows, columns=["x", "y", "grp", "v"])
    has = poly["v"].notna()
    pad = (poly[["x", "y"]].max() - poly[["x", "y"]].min()) * 0.03
    p = ggplot()
    if (~has).any():
        p += geom_polygon(poly[~has], aes(x="x", y="y", group="grp"), fill="#eeeeee", color="#888888")
    if has.any():
        p += geom_polygon(poly[has], aes(x="x", y="y", group="grp", fill="v"), color="#888888")
    if tags:
        p += geom_text(pd.DataFrame(tags, columns=["x", "y", "t"]), aes(x="x", y="y", label="t"), size=5, fontweight="bold")
    n_ok = len([k for k in values if k in known])
    p = (p + scale_fill_gradient(low="#deebf7", high="#08306b", limits=(lo, hi), name=label)
          + coord_fixed(ratio=1 / np.cos(np.deg2rad(poly["y"].mean())),             # tỉ lệ kinh độ/vĩ độ đúng
                        xlim=(poly["x"].min() - pad["x"], poly["x"].max() + pad["x"]),
                        ylim=(poly["y"].min() - pad["y"], poly["y"].max() + pad["y"]))
          + labs(title=f"{title}\n{n_ok}/{len(known)} vùng đủ dữ liệu (xám: không đủ dữ liệu)")
          + theme_void() + theme(figure_size=(8, 8), plot_title=element_text(size=11, weight="bold")))
    save(p, out, name)


# ---------------------------------------------------------------- chạy
def main(cfg):
    out = ensure_dir(FIGURES)
    cur, min_n, snaps = cfg["currency"], cfg["kpi"]["min_price_count"], cfg["snapshots"]
    last = snaps[-1]
    k1, k2, k3, k4, k5, k6, k7 = (pd.read_csv(PROC / f) for f in (
        "kpi_01_median_price.csv", "kpi_02_wifi_kitchen.csv", "kpi_03_three_night.csv", "kpi_04_price_change.csv",
        "kpi_05_superhost.csv", "kpi_06_negative_sentiment.csv", "kpi_07_aspect_complaint.csv"))
    cnt = lambda s: s.fillna(0).astype(int).astype(str)                             # đếm có thể NaN -> 0

    # KPI 1: giá trung vị theo quận x loại phòng
    s1 = k1["snapshot"].iloc[0]
    chart(out, k1, "bar", "borough", "median_price", "room_type", f"KPI 1: giá trung vị theo quận và loại phòng ({s1})", f"{cur}/đêm", "bar_price_borough")

    # KPI 2: Wi-Fi và Kitchen theo mốc
    t = k2.groupby(["snapshot", "borough"])[["n_both", "n_valid"]].sum().reset_index()
    t = pd.concat([t, k2.groupby("snapshot")[["n_both", "n_valid"]].sum().reset_index().assign(borough="Toàn mẫu")])
    chart(out, t.assign(pct=t["n_both"] / t["n_valid"].where(t["n_valid"] > 0) * 100), "line", "snapshot", "pct", "borough",
          "KPI 2: listing khai báo cả Wi-Fi và Kitchen", "% listing", "line_wifi_kitchen")

    # KPI 3: 3 đêm liên tiếp theo quận x loại phòng
    d = k3[k3["scope"] == "borough_room"]
    v = d.pivot(index="borough", columns="room_type", values="kpi3_pct")
    t = d.assign(t=fmt_pct(d["kpi3_pct"]) + "\n" + cnt(d["T"]) + "/" + cnt(d["T"].fillna(0) + d["F"].fillna(0))).pivot(index="borough", columns="room_type", values="t")
    allp = k3.loc[k3["scope"] == "ALL", "kpi3_pct"]
    heatmap(out, v, t, f"KPI 3: listing đáp ứng 3 đêm liên tiếp ({k3['snapshot'].iloc[0]}); toàn mẫu {fmt_pct(allp).iloc[0] if len(allp) else '–'}\n(ô: % và T/(T+F))",
            "% T/(T+F)", "heatmap_three_night", high=PALETTE[0])

    # KPI 4: mốc đầu so với mốc cuối, chỉ khu phố đủ >= min_n giá ở cả hai mốc
    first = k4[k4["snapshot"] == snaps[0]].set_index(["borough", "neighbourhood"])["median_price"].rename("first")
    d = k4[k4["snapshot"] == last].dropna(subset=["change_base_pct"]).join(first, on=["borough", "neighbourhood"]).dropna(subset=["first", "median_price"])
    d = d.reindex((d["median_price"] - d["first"]).abs().sort_values(ascending=False).index).head(15)
    dumbbell(out, d.assign(area=d["borough"] + " · " + d["neighbourhood"]), "area", "first", "median_price", snaps[0], last,
             f"KPI 4: giá trung vị theo khu phố, {snaps[0]} so với {last}", f"{cur}/đêm", "dumbbell_price_change")
    if geo := load_geojson(cfg):                                                    # bản đồ duy nhất: giá theo khu phố ở mốc cuối
        d = k4[(k4["snapshot"] == last) & (k4["n_valid"] >= min_n)]
        vals = {(r.borough, r.neighbourhood): (r.median_price, f"{r.borough} · {r.neighbourhood}: {r.median_price:,.0f} {cur}/đêm ({r.n_valid} giá)")
                for r in d.itertuples()}
        choropleth(out, geo, names, vals, f"KPI 4: giá trung vị theo khu phố ({last})", f"{cur}/đêm", "map_price_neighbourhood")

    # KPI 5: Superhost theo mốc
    chart(out, k5.assign(vung=np.where(k5["scope"] == "ALL", "Toàn mẫu", k5["borough"])), "line", "snapshot", "kpi5_pct", "vung",
          "KPI 5: listing thuộc Superhost", "% listing", "line_superhost")

    # KPI 6, 7: LLM
    chart(out, k6.assign(room=k6["room_type"] + " (n=" + cnt(k6["total_reviews_in_group"]) + ")"), "bar", "room",
          "negative_sentiment_pct_of_group", None, "KPI 6: review tiêu cực theo loại phòng", "% review", "bar_negative_sentiment")
    k7 = k7.assign(room=k7["room_type"] + "\n(n=" + cnt(k7["total_reviews_in_group"]) + ")")
    v = k7.pivot(index="aspect", columns="room", values="negative_pct_among_aspect_reviews")
    t = k7.assign(t=fmt_pct(k7["negative_pct_among_aspect_reviews"]) + "\n(" + cnt(k7["reviews_negative_on_aspect"]) + "/"
                  + cnt(k7["reviews_evaluating_aspect"]) + ")").pivot(index="aspect", columns="room", values="t")
    rank = v.mean(axis=1).sort_values(ascending=False).index                 # yếu tố bị chê nhiều nhất lên đầu
    heatmap(out, v.loc[rank], t.loc[rank], "KPI 7: tỉ lệ phàn nàn theo yếu tố (ô: % và chê/đánh giá yếu tố đó)", "% phàn nàn", "heatmap_aspect_complaint")
    log.info("Hình đã lưu vào %s", out)


if __name__ == "__main__":
    cli(main)
