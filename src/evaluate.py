"""Chấm LLM và baseline trên nhãn tay (accuracy, macro-F1), phân tích lỗi, ước tính chi phí xử lý hết review.

Tệp nhãn tay (config: llm.hand_labels, CSV): cột review_id + các cột nhãn bạn có thể gán:
  sentiment (positive/mixed/negative), language (mã en, es...), và từng cột <aspect>_positive/_negative
  (1 = có tín hiệu, 0 hoặc ô trống = không có), chấm riêng từng cột.
  Vẫn hỗ trợ nhãn aspect gộp (positive/mixed/negative, ô trống = không nhắc).
Cột nào không có thì bỏ qua. review_id phải còn nguyên 19 chữ số (Google Sheets/Excel hay làm tròn).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils import ROOT, ensure_dir, folder, get_logger, read_clean, read_text, snapshot_of, table_file

log = get_logger("evaluate")


def aspect_state(df, a):
    """Hai cột <a>_positive/_negative (1 hoặc trống) -> positive / negative / mixed / none."""
    pos, neg = df[f"{a}_positive"].eq("1"), df[f"{a}_negative"].eq("1")
    return pd.Series(np.select([pos & neg, pos, neg], ["mixed", "positive", "negative"], "none"), index=df.index)


def scores(y_true, y_pred):
    """(accuracy, macro-F1 trên các nhãn xuất hiện)."""
    f1s = []
    for c in sorted(set(y_true) | set(y_pred)):
        tp, fp, fn = ((y_true == c) & (y_pred == c)).sum(), ((y_true != c) & (y_pred == c)).sum(), ((y_true == c) & (y_pred != c)).sum()
        f1s.append(2 * tp / (2 * tp + fp + fn) if tp else 0.0)
    return float((y_true == y_pred).mean()), float(np.mean(f1s))


def estimate_cost(cfg, sample):
    lc = cfg["llm"]
    raw = table_file(cfg, "raw", snapshot_of(cfg, "llm_snapshot_index"), "reviews")
    if not raw.exists():
        log.warning("Không có %s -> bỏ qua ước tính chi phí", raw)
        return
    total = sum(len(c) for c in pd.read_csv(raw, usecols=["id"], chunksize=500_000))
    avg_chars = sample["comment_text"].str.len().clip(upper=lc["max_chars_per_review"]).mean()
    tin = total * (avg_chars / 4 + 400 / lc["batch_size"])                 # ~4 ký tự/token + phần hướng dẫn chia đều cho lô
    tout = total * lc["est_output_tokens_per_review"]
    pin, pout = lc.get("price_per_1m_input_usd"), lc.get("price_per_1m_output_usd")
    cost = (tin * pin + tout * pout) / 1e6 if pin is not None and pout is not None else np.nan
    row = {"total_reviews_city": total, "sample_size": len(sample), "avg_chars_per_review": round(float(avg_chars), 1),
           "est_input_tokens": int(tin), "est_output_tokens": int(tout), "est_cost_usd": cost,
           "note": "ước lượng; điền giá từ trang giá chính thức vào config (price_per_1m_*)"}
    pd.DataFrame([row]).to_csv(ensure_dir(folder(cfg, "reports")) / "llm_cost_estimate.csv", index=False)
    log.info("Ước tính chi phí: %d review toàn thành phố", total)


def run(cfg):
    proc, rep = folder(cfg, "processed"), ensure_dir(folder(cfg, "reports"))
    snap = snapshot_of(cfg, "llm_snapshot_index")
    R = read_clean(table_file(cfg, "processed", snap, "reviews_clean"))
    estimate_cost(cfg, R[R["llm_source_eligible"]])
    gold_path = ROOT / cfg["llm"]["hand_labels"]
    if not gold_path.exists():
        log.warning("Chưa có %s -> bỏ qua chấm điểm (cần >= 100 nhãn tay)", gold_path)
        return
    gold = read_text(gold_path).rename(columns=str.strip)
    gold = gold.apply(lambda s: s.str.strip().str.lower()) if len(gold) else gold
    systems = {"llm": read_text(proc / "llm_predictions.csv.gz"), "baseline": read_text(proc / "baseline_predictions.csv.gz")}
    matched = gold["review_id"].isin(systems["llm"]["review_id"]).sum()
    log.info("Nhãn tay: %d dòng, khớp review_id với mẫu: %d", len(gold), matched)
    if matched < len(gold):
        log.warning("%d review_id không khớp: kiểm tra xem Sheets/Excel có làm tròn ID dài không", len(gold) - matched)
    aspects = list(cfg["llm"]["aspects"])
    aspect_columns = [f"{a}_{s}" for a in aspects for s in ("positive", "negative")]
    labels = [c for c in ["sentiment", "language"] + aspects + aspect_columns if c in gold.columns]
    pred = {}
    for name, P in systems.items():
        P = P.set_index("review_id")
        pred[name] = pd.DataFrame({"sentiment": P["sentiment"], "language": P["language"],
                                   **{a: aspect_state(P, a) for a in aspects},
                                   **{c: P[c].replace("", "0") for c in aspect_columns if c in gold.columns}
                                   }).reindex(gold["review_id"]).fillna("missing")
    rows, errors = [], []
    for lab in labels:
        g = gold.set_index("review_id")[lab].replace("", "none") if lab in aspects else gold.set_index("review_id")[lab]
        if lab in aspect_columns:
            g = g.replace("", "0")
        for name, P in pred.items():
            acc, f1 = scores(g, P[lab])
            rows.append({"label": lab, "system": name, "n": len(g), "accuracy": round(acc, 4), "macro_f1": round(f1, 4)})
        wrong = (pred["llm"][lab] != g) | (pred["baseline"][lab] != g)
        for rid in g.index[wrong.to_numpy()]:
            errors.append({"review_id": rid, "label": lab, "gold": g[rid], "llm": pred["llm"].at[rid, lab], "baseline": pred["baseline"].at[rid, lab]})
    pd.DataFrame(rows).to_csv(rep / "eval_metrics.csv", index=False)
    text = R.set_index("id")["comment_text"]
    err = pd.DataFrame(errors, columns=["review_id", "label", "gold", "llm", "baseline"])
    err["comment"] = err["review_id"].map(text).fillna("").str.slice(0, 300)
    err.to_csv(rep / "error_analysis.csv", index=False)
    log.info("Kết quả:\n%s", pd.DataFrame(rows).to_string(index=False))
