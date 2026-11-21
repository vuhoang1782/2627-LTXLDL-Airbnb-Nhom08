"""Chấm LLM và baseline trên nhãn tay (accuracy, macro-F1), phân tích lỗi, ước tính chi phí xử lý hết review.

Tệp nhãn tay (config: llm.hand_labels, CSV): cột review_id + các cột nhãn bạn có thể gán:
  sentiment (positive/mixed/negative), language (mã en, es...), và từng cột <aspect>_positive/_negative
  (1 = có tín hiệu, 0 hoặc ô trống = không có). Mỗi aspect được chấm MỘT lần, trên nhãn gộp positive/negative/mixed/none
  suy ra từ hai cột đó (nếu tệp nhãn có sẵn cột gộp <aspect> thì dùng luôn).
Baseline (VADER) chỉ có nhãn sentiment nên chỉ được chấm ở sentiment. Cột nhãn nào không có thì bỏ qua.
review_id phải còn nguyên 19 chữ số (Google Sheets/Excel hay làm tròn).
Chạy:  python -m src.evaluate --config X.yaml
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.utils import PROC, REPORTS, ROOT, clean_file, cli, ensure_dir, get_logger, raw_file, read_clean, read_text, snapshot_of

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
    raw = raw_file(snapshot_of(cfg, "llm_snapshot_index"), "reviews")
    if not raw.exists():
        log.warning("Không có %s -> bỏ qua ước tính chi phí", raw)
        return
    total = sum(len(c) for c in pd.read_csv(raw, usecols=["id"], chunksize=500_000))
    avg_chars = sample["comment_text"].str.len().mean()                    # comment_text đã được cắt ở qa.py
    tin = total * (avg_chars / 4 + 400 / lc["batch_size"])                 # ~4 ký tự/token + phần hướng dẫn chia đều cho lô
    tout = total * lc["est_output_tokens_per_review"]
    pin, pout = lc.get("price_per_1m_input_usd"), lc.get("price_per_1m_output_usd")
    cost = (tin * pin + tout * pout) / 1e6 if pin is not None and pout is not None else np.nan
    row = {"total_reviews_city": total, "sample_size": len(sample), "avg_chars_per_review": round(float(avg_chars), 1),
           "est_input_tokens": int(tin), "est_output_tokens": int(tout), "est_cost_usd": cost,
           "note": "ước lượng; điền giá từ trang giá chính thức vào config (price_per_1m_*)"}
    pd.DataFrame([row]).to_csv(ensure_dir(REPORTS) / "llm_cost_estimate.csv", index=False)
    log.info("Ước tính chi phí: %d review toàn thành phố", total)


def main(cfg):
    rep, snap = ensure_dir(REPORTS), snapshot_of(cfg, "llm_snapshot_index")
    R = read_clean(clean_file(snap, "reviews"))
    estimate_cost(cfg, R[R["llm_source_eligible"]])
    gold_path = ROOT / cfg["llm"]["hand_labels"]
    if not gold_path.exists():
        log.warning("Chưa có %s -> bỏ qua chấm điểm (cần >= 100 nhãn tay)", gold_path)
        return
    gold = read_text(gold_path).rename(columns=str.strip)
    gold = gold.apply(lambda s: s.str.strip().str.lower()) if len(gold) else gold
    llm, base = (read_text(PROC / f).set_index("review_id") for f in ("llm_predictions.csv.gz", "baseline_predictions.csv.gz"))
    matched = gold["review_id"].isin(llm.index).sum()
    log.info("Nhãn tay: %d dòng, khớp review_id với mẫu: %d", len(gold), matched)
    if matched < len(gold):
        log.warning("%d review_id không khớp: kiểm tra xem Sheets/Excel có làm tròn ID dài không", len(gold) - matched)
    aspects, gold = list(cfg["llm"]["aspects"]), gold.set_index("review_id")

    truth, pred = {}, {"llm": {}, "baseline": {}}                           # nhãn -> Series theo review_id
    for lab in ["sentiment", "language"]:
        if lab in gold.columns:
            truth[lab], pred["llm"][lab] = gold[lab], llm[lab]
    pred["baseline"]["sentiment"] = base["sentiment"]                       # baseline chỉ có sentiment
    for a in aspects:
        if a in gold.columns:                                               # nhãn gộp có sẵn
            truth[a] = gold[a].replace("", "none")
        elif {f"{a}_positive", f"{a}_negative"} <= set(gold.columns):
            truth[a] = aspect_state(gold, a)
        else:
            continue
        pred["llm"][a] = aspect_state(llm, a)

    rows, errors = [], []
    for lab, g in truth.items():
        got = {s: p[lab].reindex(g.index).fillna("missing") for s, p in pred.items() if lab in p}
        for name, P in got.items():
            acc, f1 = scores(g, P)
            rows.append({"label": lab, "system": name, "n": len(g), "accuracy": round(acc, 4), "macro_f1": round(f1, 4)})
        wrong = pd.concat([P != g for P in got.values()], axis=1).any(axis=1)
        for rid in g.index[wrong.to_numpy()]:
            errors.append({"review_id": rid, "label": lab, "gold": g[rid], "llm": got["llm"][rid], "baseline": got["baseline"][rid] if "baseline" in got else ""})
    pd.DataFrame(rows).to_csv(rep / "eval_metrics.csv", index=False)
    text = R.set_index("id")["comment_text"]
    err = pd.DataFrame(errors, columns=["review_id", "label", "gold", "llm", "baseline"])
    err["comment"] = err["review_id"].map(text).fillna("").str.slice(0, 300)
    err.to_csv(rep / "error_analysis.csv", index=False)
    log.info("Kết quả:\n%s", pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    cli(main)
