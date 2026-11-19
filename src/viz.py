"""Hình tự sinh vào figures/: không gian, thời gian, LLM (đọc kết quả KPI đã ghi ở data/processed)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils import ensure_dir, folder, get_logger, read_clean, snapshot_of, table_file

log = get_logger("viz")


def read_kpi(cfg, name):
    p = folder(cfg, "processed") / name
    return pd.read_csv(p) if p.exists() else None


def run(cfg):
    fig_dir = ensure_dir(folder(cfg, "figures"))
    cur = cfg["currency"]

    # 1) Không gian: vị trí listing theo quận (mốc KPI 1) và giá trung vị theo quận x loại phòng
    snap = snapshot_of(cfg, "kpi1_snapshot_index")
    L = read_clean(table_file(cfg, "processed", snap, "listings_clean"))
    L = L[L["analysis_row"] & L["borough_ok"]]
    L = L.assign(lat=pd.to_numeric(L.get("latitude"), errors="coerce"), lon=pd.to_numeric(L.get("longitude"), errors="coerce")).dropna(subset=["lat", "lon"])
    if len(L):
        fig, ax = plt.subplots(figsize=(7, 7))
        for b, g in L.groupby("borough"):
            ax.scatter(g["lon"], g["lat"], s=8, label=b, alpha=0.7)
        ax.set(title=f"Vị trí listing theo quận ({snap})", xlabel="kinh độ", ylabel="vĩ độ")
        ax.set_aspect(1 / np.cos(np.deg2rad(L["lat"].mean())))
        ax.legend(markerscale=2)
        fig.savefig(fig_dir / "fig_space_listings.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    k1 = read_kpi(cfg, "kpi_01_median_price.csv")
    if k1 is not None and len(k1):
        ax = k1.pivot(index="borough", columns="room_type", values="median_price").plot(kind="bar", figsize=(8, 4))
        ax.set(title=f"KPI 1: giá trung vị theo quận và loại phòng ({snap})", ylabel=f"{cur}/đêm", xlabel="")
        ax.figure.savefig(fig_dir / "fig_space_kpi1_price.png", dpi=150, bbox_inches="tight")
        plt.close(ax.figure)

    # 2) Thời gian: KPI 2 và KPI 5 toàn mẫu qua các mốc
    k2, k5 = read_kpi(cfg, "kpi_02_wifi_kitchen.csv"), read_kpi(cfg, "kpi_05_superhost.csv")
    series = []
    if k2 is not None:
        t = k2.groupby("snapshot")[["n_both", "n_valid"]].sum()
        series.append(("KPI 2: có cả Wi-Fi và Kitchen (%)", (t["n_both"] / t["n_valid"].where(t["n_valid"] > 0) * 100)))
    if k5 is not None:
        series.append(("KPI 5: listing thuộc Superhost (%)", k5[k5["scope"] == "ALL"].set_index("snapshot")["kpi5_pct"]))
    if series:
        fig, axes = plt.subplots(1, len(series), figsize=(5 * len(series), 3.6))
        for ax, (title, s) in zip(np.atleast_1d(axes), series):
            ax.plot(s.index, s.values, marker="o")
            ax.set(title=title)
            ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        fig.savefig(fig_dir / "fig_time.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    # 3) LLM: KPI 6 và KPI 7
    k6, k7 = read_kpi(cfg, "kpi_06_negative_sentiment.csv"), read_kpi(cfg, "kpi_07_aspect_complaint.csv")
    if k6 is not None and k7 is not None:
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
        a1.bar(k6["room_type"], k6["negative_sentiment_pct_of_group"])
        a1.set(title="KPI 6: review tiêu cực (%)")
        k7.pivot(index="aspect", columns="room_type", values="negative_pct_among_aspect_reviews").plot(kind="bar", ax=a2)
        a2.set(title="KPI 7: tỉ lệ phàn nàn theo yếu tố (%)", xlabel="")
        fig.tight_layout()
        fig.savefig(fig_dir / "fig_llm.png", dpi=150, bbox_inches="tight")
        plt.close(fig)
    log.info("Hình đã lưu vào %s", fig_dir)
