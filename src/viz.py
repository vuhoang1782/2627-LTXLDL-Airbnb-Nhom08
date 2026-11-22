"""Vẽ PNG từ CSV kết quả có sẵn; thêm HTML nếu đã cài plotly.

Bản đồ chỉ đọc neighbourhoods.geojson có sẵn trong data/raw/<mốc>/, không tải dữ liệu.
"""
from __future__ import annotations

import json
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from cycler import cycler
from matplotlib.patches import Polygon

from src.utils import ensure_dir, folder, get_logger, read_clean, snapshot_of, table_file

try:
    import plotly.express as px
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:                                   # không có plotly: vẫn vẽ PNG
    px = go = None

log = get_logger("viz")
PALETTE = ["#2b4f72", "#e08a1e", "#3b8ea5", "#c75146", "#7a9e7e", "#8e6c8a"]      # bảng màu chung cho mọi hình
ROOM_COLORS = dict(zip(["Entire home/apt", "Private room"], PALETTE[:2]))
ASPECT_LABELS = {"cleanliness": "Vệ sinh", "host_friendliness": "Sự thân thiện của chủ nhà",
                 "noise": "Tiếng ồn", "amenities": "Tiện nghi", "location": "Vị trí"}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.titlesize": 12,
                     "figure.titlesize": 12, "hatch.linewidth": 0.5, "axes.spines.top": False,
                     "axes.spines.right": False, "axes.prop_cycle": cycler(color=PALETTE)})
HALO = [pe.withStroke(linewidth=2.5, foreground="white")]                          # viền trắng quanh chữ để dễ đọc trên nền màu


def read_kpi(cfg, name):
    p = folder(cfg, "processed") / name
    df = pd.read_csv(p) if p.exists() else None
    return df if df is not None and len(df) else None                              # thiếu hoặc rỗng -> None


def pct(s):
    return s.map(lambda v: f"{v:.1f}%" if v == v else "–")                         # NaN -> "–"


def kpi2_trend(k2, by_room=False):
    """Gộp tử/mẫu số, có thể tách loại phòng; lấy nhãn từ tiêu chí đã lưu cùng số liệu."""
    for col in ("required_amenities", "amenities_label"):
        if col not in k2 or k2[col].isna().any() or k2[col].nunique() != 1:
            raise ValueError("KPI 2 thiếu metadata hoặc trộn các bộ tiêu chí; hãy chạy lại bước kpi")
    keys = ["snapshot", "borough", "room_type"] if by_room else ["snapshot", "borough"]
    t = k2.groupby(keys)[["n_matched", "n_valid"]].sum().reset_index()
    if not by_room:
        t = pd.concat([t, k2.groupby("snapshot")[["n_matched", "n_valid"]].sum()
                       .reset_index().assign(borough="Toàn mẫu")], ignore_index=True)
    t["pct"] = t["n_matched"] / t["n_valid"].where(t["n_valid"] > 0) * 100
    title = "KPI 2: Tỷ lệ listing đáp ứng bộ tiện nghi yêu cầu\n" + textwrap.fill(
        f"Bộ tiện nghi: {k2['amenities_label'].iloc[0]}", width=100)
    return t, title


def save(fig, out, name, html=None):
    fig.savefig(out / f"{name}.png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    if html is not None:
        html.write_html(out / f"{name}.html", include_plotlyjs="directory")


def kpi2_chart(out, k2, colors=None):
    """Hai loại phòng dùng thang Y riêng; nhãn đầu/cuối nằm trong lề hai bên đường."""
    rooms = ["Entire home/apt", "Private room"]
    t, _ = kpi2_trend(k2, by_room=True)
    amenities = k2["amenities_label"].iloc[0].replace(" + ", " và ")
    title = f"KPI 2: Tỷ lệ listing khai báo đủ {amenities} theo quận và loại phòng"
    t = t[t["room_type"].isin(rooms)]
    if t["pct"].dropna().empty:
        return log.warning("line_amenities: không có số liệu -> bỏ qua")
    boroughs = sorted(t["borough"].unique())
    snapshots = sorted(t["snapshot"].unique())
    colors = colors or dict(zip(boroughs, PALETTE))
    note = ("Hai biểu đồ sử dụng thang đo trục Y khác nhau.\n"
            "Listing cần có tất cả tiện nghi được chọn (AND); mẫu số là n_valid.")
    x = np.arange(len(snapshots))
    limits, annotations = {}, []
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.4))
    for col, (ax, room) in enumerate(zip(axes, rooms), 1):
        wide = t[t["room_type"] == room].pivot(index="snapshot", columns="borough", values="pct")
        wide = wide.reindex(index=snapshots, columns=boroughs)
        ax.set(title=f"Loại phòng: {room}", xlabel="", ylabel="Tỷ lệ listing (%)")
        ax.set_xticks(x, snapshots, fontsize=9)
        ax.set_xlim(-0.7, len(snapshots) - 0.3)
        if wide.dropna(how="all").empty:
            continue
        lo, hi = np.nanmin(wide.to_numpy()), np.nanmax(wide.to_numpy())
        pad = max((hi - lo) * 0.12, 1)
        limits[col] = (lo - pad, hi + pad)
        ax.set_ylim(limits[col])
        for borough in boroughs:
            ax.plot(x, wide[borough], marker="o", color=colors[borough], label=borough)
        # Dàn nhãn theo Y với khoảng cách tối thiểu; X nằm ngoài đoạn có đường vẽ.
        gap = (hi - lo + 2 * pad) * 0.055
        for endpoint, side in ((0, -1), (-1, 1)):
            values = wide.iloc[endpoint].dropna().sort_values()
            if values.empty:
                continue
            label_y = values.to_numpy().copy()
            for i in range(1, len(label_y)):
                label_y[i] = max(label_y[i], label_y[i - 1] + gap)
            label_y -= max(0, label_y[-1] - (hi + pad - gap / 2))
            label_x, align = x[endpoint] + side * 0.12, "right" if side < 0 else "left"
            for (borough, value), y in zip(values.items(), label_y):
                ax.text(label_x, y, f"{value:.1f}%", color=colors[borough], ha=align, va="center", fontsize=9)
                suffix = "" if col == 1 else str(col)
                annotations.append(dict(x=label_x, y=y, text=f"{value:.1f}%", xref=f"x{suffix}", yref=f"y{suffix}",
                                        xanchor=align, font=dict(color=colors[borough], size=12), showarrow=False))
        ax.grid(axis="y", color="#e5e5e5", ls="--")
        ax.set_axisbelow(True)
    fig.suptitle(title, weight="bold", y=0.99)
    fig.legend(*axes[0].get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(0.5, 0.075),
               ncol=len(boroughs), frameon=False)
    fig.text(0.5, 0.015, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.18, 1, 1))
    html = None
    if px:
        data = t.assign(snapshot_index=t["snapshot"].map(dict(zip(snapshots, x))))
        html = px.line(data, x="snapshot_index", y="pct", color="borough", facet_col="room_type", markers=True,
                       category_orders={"room_type": rooms, "borough": boroughs, "snapshot": snapshots},
                       color_discrete_map=colors, labels={"pct": "Tỷ lệ listing (%)", "snapshot_index": ""},
                       hover_data=["snapshot"],
                       title=title.replace("\n", "<br>"), template="simple_white")
        for annotation in html.layout.annotations:
            annotation.text = "Loại phòng: " + annotation.text.split("=", 1)[-1]
        html.update_xaxes(tickvals=x, ticktext=snapshots, range=[-0.7, len(snapshots) - 0.3])
        html.update_yaxes(matches=None, showticklabels=True)
        for col, ylim in limits.items():
            html.update_yaxes(range=list(ylim), col=col)
        for annotation in annotations:
            html.add_annotation(**annotation)
        html.update_layout(legend=dict(title_text="", orientation="h", x=0.5, xanchor="center", y=-0.2),
                           width=1400, height=540, margin=dict(t=80, b=140))
        html.add_annotation(text=note.replace("\n", "<br>"), x=0.5, y=-0.4, xref="paper", yref="paper", showarrow=False)
    save(fig, out, "line_amenities", html)


# ---------------------------------------------------------------- cột / đường
def chart(out, df, kind, x, y, color, title, ylabel, name, colors=None):
    """Cột nhóm, cột ngang nhóm hoặc đường; n_valid (nếu có) ghi cùng giá trên cột."""
    wide = df.pivot(index=x, columns=color, values=y) if color else df.set_index(x)[[y]]
    if wide.dropna(how="all").empty:
        return log.warning("%s: không có số liệu -> bỏ qua", name)
    colors = colors or dict(zip(wide.columns, PALETTE))
    horizontal = kind == "barh"
    size = (10, max(4, 0.62 * len(wide) + 1.5)) if horizontal else (9.5, 5)
    ax = wide.plot(kind=kind, figsize=size, legend=False, color=[colors[c] for c in wide.columns],
                   rot=0, **({"marker": "o"} if kind == "line" else {}))
    ax.set(title=title, xlabel=ylabel if horizontal else "", ylabel="" if horizontal else ylabel)
    ax.grid(axis="x" if horizontal else "y", color="#e5e5e5", ls="--")
    ax.set_axisbelow(True)
    if kind in ("bar", "barh"):
        counts = df.pivot(index=x, columns=color, values="n_valid").reindex_like(wide) if "n_valid" in df else None
        for j, c in enumerate(ax.containers):
            labels = [f"{v:.2f}%" if horizontal else f"{v:,.1f}" for v in c.datavalues]
            if counts is not None:
                labels = [f"{label}\nn={int(n)}" for label, n in zip(labels, counts.iloc[:, j])]
            ax.bar_label(c, labels=labels, fontsize=8.5, padding=3)
        maximum = wide.max().max()
        if horizontal:
            ax.set_xlim(0, maximum * 1.16 if maximum > 0 else 1)
            ax.invert_yaxis()
        else:
            ax.set_ylim(0, maximum * 1.22 if maximum > 0 else 1)
    if kind == "line":
        for line in ax.lines:
            if line.get_label() == "Toàn mẫu":
                line.set(linestyle="--", linewidth=3)
    if color:
        ax.figure.legend(*ax.get_legend_handles_labels(), loc="lower center", ncol=len(wide.columns), frameon=False)
    ax.figure.tight_layout(rect=(0, 0.07, 1, 1))
    html = None
    if px:
        kw = dict(color=color, color_discrete_map=colors, title=title.replace("\n", "<br>"), template="simple_white")
        if kind == "line":
            html = px.line(df, x=x, y=y, markers=True, **kw)
            for trace in html.data:
                if trace.name == "Toàn mẫu":
                    trace.line.update(dash="dash", width=3)
        else:
            data = df.assign(value_label=df[y].map(lambda v: f"{v:.2f}%" if horizontal else f"{v:,.1f}"))
            if "n_valid" in df:
                data["value_label"] += "<br>n=" + df["n_valid"].astype(int).astype(str)
            html = px.bar(data, x=y if horizontal else x, y=x if horizontal else y,
                          orientation="h" if horizontal else "v", barmode="group", text="value_label", **kw)
            html.update_traces(textposition="outside", cliponaxis=False)
            if horizontal:
                html.update_xaxes(range=list(ax.get_xlim()))
                html.update_yaxes(autorange="reversed")
            else:
                html.update_yaxes(range=list(ax.get_ylim()))
        html.update_layout(legend=dict(title_text="", orientation="h", x=0.5, xanchor="center", y=-0.18),
                           margin=dict(b=100))
    save(ax.figure, out, name, html)


# ---------------------------------------------------------------- bảng nhiệt
def heatmap(out, values, text, title, label, name, cmap="YlOrRd", note=None):
    """values: bảng số (hàng x cột) để tô màu; text: bảng chuỗi cùng cỡ để ghi trong ô (ô NaN ghi '–')."""
    z = values.to_numpy(float)
    if np.isnan(z).all():
        return log.warning("%s: không có số liệu -> bỏ qua", name)
    fig, ax = plt.subplots(figsize=(1.7 * z.shape[1] + 3, 0.65 * z.shape[0] + 2))
    im = ax.imshow(z, cmap=cmap, aspect="auto")
    ax.set_xticks(range(z.shape[1]), values.columns)
    ax.set_yticks(range(z.shape[0]), values.index)
    ax.tick_params(length=0)
    ax.spines[:].set_visible(False)
    lo, hi = np.nanmin(z), np.nanmax(z)
    for (i, j), v in np.ndenumerate(z):
        ax.text(j, i, text.iat[i, j] if v == v else "–", ha="center", va="center", fontsize=9,
                color="white" if v == v and (v - lo) / ((hi - lo) or 1) > 0.6 else "black")
    fig.colorbar(im, ax=ax, label=label, shrink=0.8)
    ax.set_title(title)
    if note:
        fig.text(0.5, 0.025, note, ha="center", fontsize=9)
    fig.tight_layout(rect=(0, 0.07 if note else 0, 1, 1))
    html = None
    if go:
        html = go.Figure(go.Heatmap(z=z, x=list(values.columns), y=list(values.index), text=text.to_numpy(), texttemplate="%{text}",
                                    colorscale=cmap, colorbar_title=label))
        html.update_layout(title=title, template="simple_white", yaxis_autorange="reversed")
        if note:
            html.add_annotation(text=note, x=0.5, y=-0.15, xref="paper", yref="paper", showarrow=False)
            html.update_layout(margin=dict(b=90))
    save(fig, out, name, html)


# ---------------------------------------------------------------- so sánh giá ở đủ các mốc (quả tạ)
def dumbbell(out, df, snapshots, currency):
    """Chọn n_valid >= 10 ở mọi mốc; chỉ dịch Y để phân biệt các giá trùng/gần nhau."""
    base = "dumbbell_price_change"
    for name in (base, f"{base}_1", f"{base}_2"):
        for ext in ("png", "html"):
            (out / f"{name}.{ext}").unlink(missing_ok=True)
    counts = df.pivot(index=["borough", "neighbourhood"], columns="snapshot", values="n_valid").reindex(columns=snapshots)
    prices = df.pivot(index=["borough", "neighbourhood"], columns="snapshot", values="median_price").reindex(columns=snapshots)
    d = prices.loc[counts.ge(10).all(axis=1)].sort_values(snapshots[-1], ascending=False)
    log.info("KPI 4: %d khu phố có n_valid >= 10 tại cả %d snapshot", len(d), len(snapshots))
    if d.empty:
        return log.warning("%s: không có khu phố đủ điều kiện -> bỏ qua", base)
    if d.isna().any().any():
        log.warning("KPI 4: có khu phố đủ n_valid nhưng thiếu median_price; giữ hàng và để trống điểm thiếu")
    lo, hi = np.nanmin(d.to_numpy()), np.nanmax(d.to_numpy())
    span = (hi - lo) or max(abs(hi), 1)
    xlim = (max(0, lo - span * 0.06), hi + span * 0.07)
    # 0.52 inch mỗi hàng; nếu vượt 18 inch thì chia đôi, giữ chung thang X.
    parts = np.array_split(np.arange(len(d)), 2) if 0.52 * len(d) + 2.1 > 18 else [np.arange(len(d))]
    note = f"Khu phố có ít nhất 10 listing hợp lệ tại cả {len(snapshots)} mốc"
    for part, rows in enumerate(parts, 1):
        block = d.iloc[rows]
        pos = np.arange(len(block))
        ys = np.tile(pos[:, None], (1, len(snapshots))).astype(float)
        for i, values in enumerate(block.to_numpy()):
            order = np.argsort(values)
            clusters = np.split(order, np.flatnonzero(np.diff(values[order]) >= span * 0.025) + 1)
            for cluster in clusters:
                if len(cluster) > 1:
                    ys[i, cluster] += np.linspace(-0.21, 0.21, len(cluster))
        fig, ax = plt.subplots(figsize=(11.5, 0.52 * len(block) + 2.1))
        ax.hlines(pos, block.min(axis=1), block.max(axis=1), color="#9aa5b1", lw=2.2)
        for j, snap in enumerate(snapshots):
            ax.scatter(block[snap], ys[:, j], s=72 if j in (0, len(snapshots) - 1) else 44,
                       color=PALETTE[j % len(PALETTE)], edgecolor="white", linewidth=0.5, label=snap, zorder=3)
        labels = [f"{row.iloc[-1]:,.2f} ({row.iloc[-1] - row.iloc[0]:+,.2f})" for _, row in block.iterrows()]
        for i, label in enumerate(labels):
            ax.text(1.02, i, label, transform=ax.get_yaxis_transform(), va="center", fontsize=9)
        ax.text(1.02, 1.015, "Cuối kỳ (Δ so với đầu kỳ)", transform=ax.transAxes, fontsize=9)
        areas = [f"{borough} · {neighbourhood}" for borough, neighbourhood in block.index]
        ax.set_yticks(pos, areas)
        ax.set(xlabel=f"{currency}/đêm", xlim=xlim, ylim=(len(block) - 0.5, -0.5))
        ax.grid(axis="x", color="#e5e5e5", ls="--")
        ax.set_axisbelow(True)
        title = f"KPI 4: Giá trung vị theo khu phố ({len(d)} khu phố)"
        fig.suptitle(title, y=0.99)
        fig.legend(*ax.get_legend_handles_labels(), loc="lower center", bbox_to_anchor=(0.5, 0.025),
                   ncol=len(snapshots), frameon=False)
        fig.text(0.5, 0.01, note, ha="center", fontsize=9)
        fig.tight_layout(rect=(0, 0.065, 1, 1))
        html = None
        if go:
            lx = [v for low, high in zip(block.min(axis=1), block.max(axis=1)) for v in (low, high, None)]
            ly = [v for i in pos for v in (i, i, None)]
            html = go.Figure(go.Scatter(x=lx, y=ly, mode="lines", line=dict(color="#9aa5b1", width=2),
                                        showlegend=False, hoverinfo="skip"))
            for j, snap in enumerate(snapshots):
                html.add_trace(go.Scatter(x=block[snap], y=ys[:, j], mode="markers", name=snap, text=areas,
                                          marker=dict(color=PALETTE[j % len(PALETTE)], size=10 if j in (0, len(snapshots) - 1) else 8)))
            html.add_trace(go.Scatter(x=[hi + span * 0.1] * len(block), y=pos, text=labels, mode="text",
                                      textposition="middle right", showlegend=False, hoverinfo="skip"))
            html.update_layout(title=title, xaxis_title=f"{currency}/đêm", template="simple_white",
                               height=int(fig.get_figheight() * 100), margin=dict(l=260, b=90),
                               legend=dict(orientation="h", x=0.5, xanchor="center", y=-0.08))
            html.update_xaxes(range=[xlim[0], hi + span * 0.8])
            html.update_yaxes(tickvals=pos, ticktext=areas, range=[len(block) - 0.5, -0.5])
            html.add_annotation(text=note, x=0.5, y=-0.12, xref="paper", yref="paper", showarrow=False)
            html.update_layout(margin=dict(b=130))
        save(fig, out, base if len(parts) == 1 else f"{base}_{part}", html)


# ---------------------------------------------------------------- bản đồ từ geojson
def load_geojson(cfg):
    """Chỉ đọc GeoJSON có sẵn; bước visualization không tải dữ liệu."""
    snaps = cfg["snapshots"]
    path = next((p for s in reversed(snaps) if (p := folder(cfg, "raw", s) / "neighbourhoods.geojson").exists()), None)
    if path is None:
        log.warning("Không có neighbourhoods.geojson -> bỏ qua bản đồ giá")
        return None
    geo = json.loads(path.read_text(encoding="utf-8"))
    for i, f in enumerate(geo["features"]):
        f["properties"]["fid"] = str(i)                            # mã riêng của từng vùng, để plotly nối giá trị với hình
    return geo


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


def fit(ax, pts):
    """Khung nhìn vừa các điểm (lề 3%) và tỉ lệ kinh độ/vĩ độ đúng."""
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    pad = (hi - lo) * 0.03
    ax.set(xlim=(lo[0] - pad[0], hi[0] + pad[0]), ylim=(lo[1] - pad[1], hi[1] + pad[1]))
    ax.set_aspect(1 / np.cos(np.deg2rad(pts[:, 1].mean())))
    ax.set_axis_off()


def choropleth(out, geo, k1, snapshot, currency, min_n):
    """Hai loại phòng chung thang màu; giữ quy tắc bản đồ n_valid >= min_n."""
    rooms = list(ROOM_COLORS)
    valid = k1[(k1["n_valid"] >= min_n) & k1["room_type"].isin(rooms)].dropna(subset=["median_price"])
    if valid.empty:
        return log.warning("map_price_borough: chưa quận nào đủ dữ liệu -> bỏ qua")
    lo, hi = np.nanpercentile(valid["median_price"], [5, 95])
    norm = plt.Normalize(lo, hi if hi > lo else lo + 1)
    cmap = matplotlib.colors.LinearSegmentedColormap.from_list(
        "Blues_truncated", plt.get_cmap("Blues")(np.linspace(0.2, 1, 256)))
    pts = {}
    for f in geo["features"]:
        pts.setdefault(names(f)[0], []).extend(rings(f["geometry"]))
    allpts = np.vstack([ring for rs in pts.values() for ring in rs])
    title = f"KPI 1: Giá trung vị theo quận ({snapshot})"
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 6.7))
    html = make_subplots(rows=1, cols=2, specs=[[{"type": "geo"}, {"type": "geo"}]], subplot_titles=rooms) if go else None
    for col, (ax, room) in enumerate(zip(axes, rooms), 1):
        values = valid[valid["room_type"] == room].set_index("borough")["median_price"].to_dict()
        if lost := set(values) - set(pts):
            log.warning("map_price_borough: tên quận không khớp GeoJSON: %s", sorted(lost))
        for borough, rs in pts.items():
            color = cmap(norm(values[borough])) if borough in values else None
            for ring in rs:
                ax.add_patch(Polygon(ring, closed=True, facecolor=color if color is not None else "#eeeeee",
                                     hatch=None if color is not None else "////", linewidth=0.5,
                                     edgecolor="#8093A6" if color is not None else "#888888"))
        fit(ax, allpts)
        ax.set_title(room)
        centers = {}
        for borough in values.keys() & pts.keys():
            ring = biggest(pts[borough])
            cx, cy = (ring.min(axis=0) + ring.max(axis=0)) / 2
            centers[borough] = (cx, cy)
            ax.text(cx, cy, f"{borough}\n{values[borough]:,.1f}", ha="center", va="center",
                    fontsize=9, weight="bold", path_effects=HALO)
        if html is not None:
            for has_data in (False, True):
                fs = [f for f in geo["features"] if (names(f)[0] in values) == has_data]
                html.add_trace(go.Choropleth(
                    geojson=geo, featureidkey="properties.fid", locations=[f["properties"]["fid"] for f in fs],
                    z=[values[names(f)[0]] if has_data else 0 for f in fs],
                    coloraxis="coloraxis" if has_data else None, showscale=False,
                    colorscale=None if has_data else [[0, "#ddd"], [1, "#ddd"]],
                    marker_line_color="#8093A6" if has_data else "#888888", marker_line_width=0.5,
                    text=[f"{names(f)[0]}: {values[names(f)[0]]:,.1f} {currency}/đêm" if has_data
                          else f"{names(f)[0]}: không đủ dữ liệu" for f in fs],
                    hovertemplate="%{text}<extra></extra>"), row=1, col=col)
            html.add_trace(go.Scattergeo(lon=[p[0] for p in centers.values()], lat=[p[1] for p in centers.values()],
                                        text=[f"{b}<br>{values[b]:,.1f}" for b in centers], mode="text", showlegend=False), row=1, col=col)
    fig.suptitle(title, y=0.98)
    fig.text(0.5, 0.025, "Gạch chéo xám: không đủ dữ liệu", ha="center", fontsize=9)
    fig.subplots_adjust(left=0.01, right=0.93, bottom=0.07, top=0.9, wspace=0.02)
    fig.colorbar(plt.cm.ScalarMappable(norm, cmap), ax=axes, shrink=0.7, pad=0.02, label=f"{currency}/đêm")
    if html is not None:
        html.update_geos(fitbounds="locations", visible=False)
        colorscale = [[t, matplotlib.colors.to_hex(cmap(t))] for t in np.linspace(0, 1, 256)]
        html.update_layout(title=title, coloraxis=dict(cmin=norm.vmin, cmax=norm.vmax, colorscale=colorscale,
                                                      colorbar_title=f"{currency}/đêm"), margin=dict(l=0, r=0, t=70, b=30))
    save(fig, out, "map_price_borough", html)


def listings_map(cfg, out, geo):
    """Vị trí từng listing (mốc KPI 1), tô màu theo quận, vẽ trên đường viền khu vực nếu có."""
    snap = snapshot_of(cfg, "kpi1_snapshot_index")
    L = read_clean(table_file(cfg, "processed", snap, "listings_clean"))
    L = L[L["analysis_row"] & L["borough_ok"]]
    L = L.assign(lon=pd.to_numeric(L["longitude"], errors="coerce"), lat=pd.to_numeric(L["latitude"], errors="coerce")).dropna(subset=["lon", "lat"])
    if L.empty:
        return
    fig, ax = plt.subplots(figsize=(8, 8))
    allpts = [L[["lon", "lat"]].to_numpy()]
    for f in (geo or {"features": []})["features"]:
        for ring in rings(f["geometry"]):
            ax.add_patch(Polygon(ring, closed=True, fill=False, edgecolor="#bbbbbb", lw=0.4))
            allpts.append(ring)
    for b, g in L.groupby("borough"):
        ax.scatter(g["lon"], g["lat"], s=10, alpha=0.7, label=f"{b} ({len(g)})")
    fit(ax, np.vstack(allpts))
    ax.set_title(f"Vị trí {len(L)} listing theo quận ({snap})")
    ax.legend(frameon=False, markerscale=2)
    save(fig, out, "map_listings")


def negative_chart(out, k6):
    """Tỷ lệ review tiêu cực, kèm tử số/mẫu số của từng loại phòng."""
    d = k6.set_index("room_type").reindex(ROOM_COLORS).dropna(subset=["negative_sentiment_pct_of_group"])
    if d.empty:
        return log.warning("bar_negative_sentiment: không có số liệu -> bỏ qua")
    values = d["negative_sentiment_pct_of_group"]
    labels = [f"{r.negative_sentiment_pct_of_group:.2f}%  ({int(r.reviews_negative_sentiment)}/{int(r.total_reviews_in_group)})"
              for r in d.itertuples()]
    fig, ax = plt.subplots(figsize=(9, 2.8))
    bars = ax.barh(d.index, values, color=[ROOM_COLORS[room] for room in d.index], height=0.5)
    ax.bar_label(bars, labels=labels, padding=5, fontsize=10)
    maximum = values.max()
    ax.set(xlim=(0, maximum * 1.5 if maximum > 0 else 1), xlabel="% review",
           title="KPI 6: Review tiêu cực theo loại phòng")
    ax.invert_yaxis()
    ax.grid(axis="x", color="#e5e5e5", ls="--")
    ax.set_axisbelow(True)
    fig.tight_layout()
    html = None
    if px:
        html = px.bar(d.reset_index().assign(value_label=labels), y="room_type", x=values.name,
                      color="room_type", color_discrete_map=ROOM_COLORS, orientation="h", text="value_label",
                      title="KPI 6: Review tiêu cực theo loại phòng", template="simple_white")
        html.update_traces(textposition="outside", cliponaxis=False)
        html.update_layout(showlegend=False, height=280, xaxis_title="% review", yaxis_title="")
        html.update_xaxes(range=list(ax.get_xlim()))
        html.update_yaxes(autorange="reversed")
    save(fig, out, "bar_negative_sentiment", html)


# ---------------------------------------------------------------- chạy
def run(cfg):
    out = ensure_dir(folder(cfg, "figures"))
    cur, min_n, snaps = cfg["currency"], cfg["kpi"]["min_price_count"], cfg["snapshots"]
    k1, k2, k3, k4, k5, k6, k7 = (read_kpi(cfg, f) for f in (
        "kpi_01_median_price.csv", "kpi_02_amenities.csv", "kpi_03_three_night.csv", "kpi_04_price_change.csv",
        "kpi_05_superhost.csv", "kpi_06_negative_sentiment.csv", "kpi_07_aspect_complaint.csv"))
    geo = load_geojson(cfg)
    cnt = lambda s: s.fillna(0).astype(int).astype(str)                             # đếm có thể NaN -> 0
    boroughs = sorted(set(k2["borough"].dropna() if k2 is not None else []) |
                      set(k5["borough"].dropna() if k5 is not None else []))
    colors = {b: PALETTE[i % len(PALETTE)] for i, b in enumerate(boroughs)}
    for name in ("map_price_entire_home_apt", "map_price_private_room", "map_price_neighbourhood"):
        for ext in ("png", "html"):
            (out / f"{name}.{ext}").unlink(missing_ok=True)

    # ---- KHÔNG GIAN
    listings_map(cfg, out, geo)
    if k1 is not None:
        s1 = k1["snapshot"].iloc[0]
        chart(out, k1, "bar", "borough", "median_price", "room_type", f"KPI 1: Giá trung vị theo quận và loại phòng ({s1})",
              f"{cur}/đêm", "bar_price_borough", colors=ROOM_COLORS)
        if geo:
            choropleth(out, geo, k1, s1, cur, min_n)

    # ---- THỜI GIAN
    if k4 is not None:
        dumbbell(out, k4, snaps, cur)
    if k2 is not None:
        kpi2_chart(out, k2, colors)
    if k5 is not None:
        chart(out, k5.assign(vung=np.where(k5["scope"] == "ALL", "Toàn mẫu", k5["borough"])), "line", "snapshot", "kpi5_pct", "vung",
              "KPI 5: Listing thuộc Superhost", "% listing", "line_superhost", colors={**colors, "Toàn mẫu": "#444444"})
    if k3 is not None and (k3["scope"] == "borough_room").any():
        d = k3[k3["scope"] == "borough_room"]
        v = d.pivot(index="borough", columns="room_type", values="kpi3_pct")
        t = d.assign(t=pct(d["kpi3_pct"]) + "\n" + cnt(d["T"]) + "/" + cnt(d["T"].fillna(0) + d["F"].fillna(0))).pivot(index="borough", columns="room_type", values="t")
        allp = k3.loc[k3["scope"] == "ALL", "kpi3_pct"]
        heatmap(out, v, t, f"KPI 3: Đáp ứng ba đêm liên tiếp\n{k3['snapshot'].iloc[0]} · Toàn mẫu: {pct(allp).iloc[0] if len(allp) else '–'}",
                "Tỷ lệ đáp ứng (%)", "heatmap_three_night", cmap="Blues",
                note="Tỷ lệ = T/(T+F); U không tính vào mẫu số")

    # ---- LLM
    if k6 is not None:
        negative_chart(out, k6)
    if k7 is not None:
        k7 = k7.assign(room=k7["room_type"] + "\n(n=" + cnt(k7["total_reviews_in_group"]) + ")")
        v = k7.pivot(index="aspect", columns="room", values="negative_pct_among_aspect_reviews")
        t = k7.assign(t=pct(k7["negative_pct_among_aspect_reviews"]) + "\n(" + cnt(k7["reviews_negative_on_aspect"]) + "/"
                      + cnt(k7["reviews_evaluating_aspect"]) + ")").pivot(index="aspect", columns="room", values="t")
        order = v.mean(axis=1).sort_values(ascending=False).index                # yếu tố bị chê nhiều nhất lên đầu
        heatmap(out, v.loc[order].rename(index=ASPECT_LABELS), t.loc[order].rename(index=ASPECT_LABELS),
                "KPI 7: Tỷ lệ phàn nàn theo khía cạnh", "% phàn nàn", "heatmap_aspect_complaint")
    ev = folder(cfg, "reports") / "eval_metrics.csv"
    if ev.exists():
        e = pd.read_csv(ev)
        e["system"] = e["system"].replace({"baseline": "Baseline", "llm": "LLM"})
        for col, title, name in (("accuracy", "Độ chính xác so với nhãn tay", "bar_eval_accuracy"), ("macro_f1", "F1 (macro) so với nhãn tay", "bar_eval_f1")):
            chart(out, e.assign(**{col: e[col] * 100}), "barh", "label", col, "system", f"{title}: LLM và baseline", "%", name,
                  colors={"Baseline": PALETTE[0], "LLM": PALETTE[1]})
    log.info("Hình đã lưu vào %s", out)
