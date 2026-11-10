"""Bước 8: sinh hình tự động vào figures/ (không gian, thời gian, LLM)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from src.utils import ensure_dir, folder, get_logger, price_col, table_file

log = get_logger("viz")


def _read(cfg, name):
    p = folder(cfg, "processed") / name
    return pd.read_csv(p) if p.exists() else None


def run(cfg):
    fig_dir = ensure_dir(folder(cfg, "figures"))
    snaps, last, pcol, cur = cfg["snapshots"], cfg["snapshots"][-1], price_col(cfg), cfg["currency"]
    area_col = cfg["kpi"]["area_col"]
    L = pd.read_csv(table_file(cfg, "processed", last, "listings"), low_memory=False)
    L["qa_flags"] = L["qa_flags"].fillna("")

    # 1) Không gian: bản đồ điểm, màu theo giá (log), mốc cuối
    ok = L[~L["qa_flags"].str.contains("price_missing|price_outlier|bad_coords")]
    if len(ok):
        fig, ax = plt.subplots(figsize=(7, 7))
        sc = ax.scatter(ok["longitude"], ok["latitude"], c=np.log10(ok[pcol]), s=8, cmap="viridis", alpha=0.7)
        fig.colorbar(sc, ax=ax, label=f"log10({pcol})")
        ax.set(title=f"Vị trí và giá listing ({last})", xlabel="kinh độ", ylabel="vĩ độ")
        ax.set_aspect(1 / np.cos(np.deg2rad(ok["latitude"].mean())))
        fig.savefig(fig_dir / "fig_spatial_price.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    # 2) Không gian: giá trung vị theo khu vực
    k1 = _read(cfg, "kpi_median_price_by_area.csv")
    if k1 is not None:
        top = k1[k1["area"] != "ALL"].nlargest(15, "value").sort_values("value")
        if len(top):
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.barh(top["area"], top["value"])
            ax.set(title=f"Giá trung vị theo khu vực, 15 khu cao nhất ({last})", xlabel=f"{cur}/đêm")
            fig.savefig(fig_dir / "fig_price_by_area.png", dpi=150, bbox_inches="tight")
            plt.close(fig)

    # 3) Thời gian: các KPI toàn thành phố qua các mốc
    series = [("kpi_entire_home_share.csv", "Tỉ lệ nhà nguyên căn"),
              ("kpi_unavailable_day_rate.csv", "Tỉ lệ ngày không còn trống"),
              ("kpi_zero_review_share.csv", "Tỉ lệ listing chưa có review")]
    frames = [(t, _read(cfg, f)) for f, t in series]
    frames = [(t, d[d["area"] == "ALL"]) for t, d in frames if d is not None]
    if frames:
        fig, axes = plt.subplots(1, len(frames), figsize=(4.5 * len(frames), 3.6))
        axes = np.atleast_1d(axes)
        for ax, (title, d) in zip(axes, frames):
            ax.plot(d["snapshot"], d["value"], marker="o")
            ax.set(title=title)
            ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        fig.savefig(fig_dir / "fig_time_series.png", dpi=150, bbox_inches="tight")
        plt.close(fig)

    # 4) LLM: cảm xúc theo khu vực + khía cạnh
    path = folder(cfg, "processed") / "llm_results.csv"
    if path.exists() and path.stat().st_size > 0:
        res = pd.read_csv(path, dtype={"review_id": "int64", "listing_id": "int64"}).dropna(subset=["sentiment"])
        res[area_col] = res["listing_id"].map(L.set_index("id")[area_col])
        counts = res.groupby(area_col).size()
        keep = counts[counts >= cfg["kpi"]["min_area_reviews"]].nlargest(12).index
        if len(keep):
            share = (res[res[area_col].isin(keep)].groupby([area_col, "sentiment"]).size()
                     .unstack(fill_value=0))
            share = share.div(share.sum(axis=1), axis=0)
            share = share.reindex(columns=[c for c in cfg["llm"]["allowed_sentiments"] if c in share.columns])
            ax = share.plot(kind="barh", stacked=True, figsize=(8, 5))
            ax.set(title="Cảm xúc review theo khu vực (LLM)", xlabel="tỉ lệ")
            ax.figure.savefig(fig_dir / "fig_llm_sentiment_by_area.png", dpi=150, bbox_inches="tight")
            plt.close(ax.figure)
        pos = res["aspects_positive"].fillna("").str.split("|").explode().replace("", np.nan).dropna().value_counts()
        neg = res["aspects_negative"].fillna("").str.split("|").explode().replace("", np.nan).dropna().value_counts()
        asp = pd.DataFrame({"khen": pos, "chê": neg}).fillna(0)
        if len(asp):
            ax = asp.plot(kind="bar", figsize=(8, 4))
            ax.set(title="Khía cạnh được khen/chê (LLM)", ylabel="số lần nhắc")
            ax.figure.savefig(fig_dir / "fig_llm_aspects.png", dpi=150, bbox_inches="tight")
            plt.close(ax.figure)
    else:
        log.warning("Chưa có llm_results.csv -> bỏ qua hình LLM")
    log.info("Hình đã lưu vào %s", fig_dir)
