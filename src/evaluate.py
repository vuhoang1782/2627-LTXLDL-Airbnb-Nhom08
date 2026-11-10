"""Chấm LLM và baseline trên nhãn tay (accuracy, F1), phân tích lỗi, ước tính chi phí xử lý hết review của thành phố."""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.llm import select_sample
from src.utils import ensure_dir, folder, get_logger, table_file

log = get_logger("evaluate")


def metrics(y_true, y_pred, labels):
    rows = []
    for c in labels:
        tp = int(((y_true == c) & (y_pred == c)).sum())
        fp = int(((y_true != c) & (y_pred == c)).sum())
        fn = int(((y_true == c) & (y_pred != c)).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        rows.append({"label": c, "precision": p, "recall": r, "f1": f, "support": int((y_true == c).sum())})
    per = pd.DataFrame(rows)
    return float((y_true == y_pred).mean()), float(per["f1"].mean()), per


def make_template(cfg):
    """Tạo tệp mẫu để nhóm gán nhãn tay (cột label để trống)."""
    sample = select_sample(cfg)
    hand = sample[sample["nhan_tay"].fillna(False).astype(bool)] if "nhan_tay" in sample.columns else sample.head(0)
    if hand.empty:
        hand = sample.head(cfg["llm"]["hand_label_size"])
    path = folder(cfg, "samples") / "hand_labels_template.csv"
    ensure_dir(path.parent)
    pd.DataFrame({"review_id": hand["id"], "label": "", "comment": hand["comment_clean"].str.slice(0, 400)}).to_csv(path, index=False)
    log.info("Đã tạo %s (%d review). Điền cột label (positive/mixed/negative) rồi lưu thành %s",
             path, len(hand), cfg["llm"]["hand_labels"])


def estimate_cost(cfg):
    lc = cfg["llm"]
    sample = select_sample(cfg)
    raw = table_file(cfg, "raw", cfg["snapshots"][-1], "reviews")
    if not raw.exists():
        log.warning("Không có %s -> bỏ qua ước tính chi phí", raw)
        return
    total = 0
    for chunk in pd.read_csv(raw, usecols=["id"], chunksize=500_000):
        total += len(chunk)
    avg_chars = float(sample["comment_clean"].str.len().clip(upper=lc["max_chars_per_review"]).mean())
    in_per_review = avg_chars / 4 + 250 / lc["batch_size"]  # ~4 ký tự/token + phần hướng dẫn chia đều cho lô
    out_per_review = lc["est_output_tokens_per_review"]
    tin, tout = total * in_per_review, total * out_per_review
    pin, pout = lc.get("price_per_1m_input_usd"), lc.get("price_per_1m_output_usd")
    cost = (tin * pin + tout * pout) / 1e6 if pin is not None and pout is not None else np.nan
    row = {"total_reviews_city": total, "sample_size": len(sample), "avg_chars_per_review": round(avg_chars, 1),
           "est_input_tokens": int(tin), "est_output_tokens": int(tout),
           "price_per_1m_input_usd": pin, "price_per_1m_output_usd": pout, "est_cost_usd": cost,
           "note": "ước lượng ~4 ký tự/token; điền giá từ trang giá chính thức của nhà cung cấp vào cấu hình"}
    out = ensure_dir(folder(cfg, "reports")) / "llm_cost_estimate.csv"
    pd.DataFrame([row]).to_csv(out, index=False)
    log.info("Ước tính chi phí -> %s (tổng review thành phố: %d)", out, total)


def run(cfg, template_only=False):
    lc = cfg["llm"]
    if template_only:
        make_template(cfg)
        return
    import os
    if not os.path.exists(lc["hand_labels"]):
        log.warning("Chưa có %s -> tạo tệp mẫu để gán nhãn, bỏ qua bước chấm điểm", lc["hand_labels"])
        make_template(cfg)
        estimate_cost(cfg)
        return
    labels = list(lc["allowed_sentiments"])
    gold = pd.read_csv(lc["hand_labels"], dtype={"review_id": "int64"})
    gold["label"] = gold["label"].astype(str).str.strip().str.lower()
    gold = gold[gold["label"].isin(labels)][["review_id", "label"]]
    if len(gold) < 100:
        log.warning("Chỉ có %d nhãn tay hợp lệ (đề yêu cầu >= 100)", len(gold))
    proc = folder(cfg, "processed")
    llm = pd.read_csv(proc / "llm_results.csv", dtype={"review_id": "int64"})
    base = pd.read_csv(proc / "baseline_results.csv", dtype={"review_id": "int64"})
    df = (gold.merge(llm[["review_id", "sentiment"]].rename(columns={"sentiment": "llm"}), on="review_id", how="left")
              .merge(base[["review_id", "sentiment"]].rename(columns={"sentiment": "baseline"}), on="review_id", how="left"))
    n_missing = int(df["llm"].isna().sum())
    if n_missing:
        log.warning("%d review có nhãn tay nhưng chưa có kết quả LLM (tính là sai)", n_missing)

    rows, conf = [], {}
    for system in ("llm", "baseline"):
        pred = df[system].fillna("none")
        acc, macro, per = metrics(df["label"], pred, labels)
        rows.append({"system": system, "n": len(df), "accuracy": round(acc, 4), "macro_f1": round(macro, 4),
                     **{f"f1_{r.label}": round(r.f1, 4) for r in per.itertuples()}})
        conf[system] = pd.crosstab(df["label"], pred)
        conf[system].to_csv(ensure_dir(folder(cfg, "reports")) / f"confusion_{system}.csv")
    rep = ensure_dir(folder(cfg, "reports"))
    pd.DataFrame(rows).to_csv(rep / "eval_metrics.csv", index=False)

    text = select_sample(cfg)[["id", "comment_clean"]].rename(columns={"id": "review_id"})
    err = df.merge(text, on="review_id", how="left")
    err = err[(err["llm"] != err["label"]) | (err["baseline"] != err["label"])].copy()
    err["error_type"] = np.where((err["llm"] != err["label"]) & (err["baseline"] != err["label"]), "both_wrong",
                                 np.where(err["llm"] != err["label"], "llm_wrong", "baseline_wrong"))
    err["comment_clean"] = err["comment_clean"].fillna("").str.slice(0, 300)
    err.to_csv(rep / "error_analysis.csv", index=False)
    log.info("Kết quả:\n%s", pd.DataFrame(rows).to_string(index=False))
    estimate_cost(cfg)
