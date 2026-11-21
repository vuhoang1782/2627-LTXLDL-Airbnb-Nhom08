"""Baseline KHÔNG dùng LLM: VADER (từ điển cảm xúc tiếng Anh có sẵn) + luật ngưỡng theo mệnh đề, chỉ cho nhãn sentiment.

Ý tưởng tách mệnh đề và ngưỡng cố định lấy từ baseline của Quốc Cường (VADER).
Ngưỡng nằm ở mục `baseline:` của config (thr, mixed_min, default), CỐ ĐỊNH TRƯỚC, KHÔNG chỉnh theo nhãn tay.
Chạy:  python -m src.baseline --config X.yaml      Kiểm thử: python -m pytest tests
"""
import re

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from src.llm import source_reviews, to_rows
from src.utils import PROC, cli, ensure_dir, get_logger, snapshot_of

log = get_logger("baseline")
VADER = SentimentIntensityAnalyzer()
CLAUSE = re.compile(r"(?<=[.!?])\s+|\b(?:but|however|although|though)\b", re.I)    # tách câu và mệnh đề đối lập


def score(s):
    return VADER.polarity_scores(s)["compound"]        # [-1, 1]; VADER tự xử lý phủ định, từ nhấn mạnh, dấu chấm than


def sentiment_of(text, B):
    sc = [score(c) for c in CLAUSE.split(text) if c and c.strip()] or [0]
    if max(sc) >= B["mixed_min"] and min(sc) <= -B["mixed_min"]:    # có mệnh đề khen rõ VÀ mệnh đề chê rõ (không để triệt tiêu khi cộng)
        return "mixed"
    total = score(text)
    return "positive" if total >= B["thr"] else "negative" if total <= -B["thr"] else B["default"]   # không có tín hiệu: nhãn mặc định


def predict(text, B):
    """Trả về dict cùng dạng với đầu ra của LLM (chỉ có sentiment)."""
    text = text.replace("\u2019", "'")                  # nháy cong ’ -> nháy thẳng: VADER chỉ nhận ra phủ định như wasn't với nháy thẳng
    return {"sentiment": sentiment_of(text, B)}


def main(cfg, limit=None):
    src = source_reviews(cfg, limit)
    outs = [predict(t, cfg["baseline"]) for t in src["comment_text"]]
    df = to_rows(cfg, snapshot_of(cfg, "llm_snapshot_index"), src, outs, provider="baseline", model="vader")
    path = ensure_dir(PROC) / "baseline_predictions.csv.gz"
    df.to_csv(path, index=False)
    log.info("Baseline VADER: %d review -> %s (%s)", len(df), path.name, df["sentiment"].value_counts().to_dict())


if __name__ == "__main__":
    cli(main)
