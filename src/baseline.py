"""Baseline KHÔNG dùng LLM: VADER (từ điển cảm xúc tiếng Anh có sẵn) + luật ngưỡng theo mệnh đề.

Ý tưởng tách mệnh đề và ngưỡng cố định lấy từ baseline của Quốc Cường (VADER). Bản này mở rộng thêm khía cạnh (từ khoá, xét theo
mệnh đề) và ngôn ngữ (từ dừng) để so với LLM ở cả ba loại nhãn: sentiment, aspect, language.
Ngưỡng nằm ở mục `baseline:` của config, CỐ ĐỊNH TRƯỚC, KHÔNG chỉnh theo nhãn tay.
Chạy thử không cần mạng/khoá:  python -m src.baseline
"""
from __future__ import annotations

import re

import pandas as pd
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from src.utils import ensure_dir, folder, get_logger

log = get_logger("baseline")
DEFAULTS = {"thr": 0.05, "mixed_min": 0.25, "default": "positive"}
VADER = SentimentIntensityAnalyzer()
CLAUSE = re.compile(r"(?<=[.!?])\s+|\b(?:but|however|although|though)\b", re.I)    # tách câu và mệnh đề đối lập
STOPWORDS = {
    "en": set("the and was is were very with for you our this that had have but great place stay".split()),
    "es": set("el la los las y fue muy con para una un que estuvo lugar excelente nos".split()),
    "fr": set("le la les et était très avec pour une un que nous appartement séjour".split()),
    "de": set("der die das und war sehr mit für ein eine wir wohnung aufenthalt nicht".split()),
    "pt": set("o a os as e foi muito com para um uma que nós apartamento estadia não".split()),
    "it": set("il lo la gli le e era molto con per un una che noi appartamento soggiorno non".split()),
}

#cuong
def score(s):
    return VADER.polarity_scores(s)["compound"]        # [-1, 1]; VADER tự xử lý phủ định, từ nhấn mạnh, dấu chấm than


def clauses(text):
    return [c for c in CLAUSE.split(text) if c and c.strip()]


def sentiment_of(text, B):
    sc = [score(c) for c in clauses(text)] or [0]
    if max(sc) >= B["mixed_min"] and min(sc) <= -B["mixed_min"]:    # có mệnh đề khen rõ VÀ mệnh đề chê rõ (không để triệt tiêu khi cộng)
        return "mixed"
    total = score(text)
    return "positive" if total >= B["thr"] else "negative" if total <= -B["thr"] else B["default"]   # không có tín hiệu: nhãn mặc định


def aspects_of(text, aspects, B):
    """Mỗi mệnh đề có từ khoá của khía cạnh nào thì lấy chiều khen/chê của chính mệnh đề đó."""
    good, bad = [], []
    for clause in clauses(text):
        s = score(clause)
        for code, a in aspects.items():
            if any(k in clause.lower() for k in a["keywords"]):
                if s >= B["thr"] and code not in good:
                    good.append(code)
                elif s <= -B["thr"] and code not in bad:
                    bad.append(code)
    return good, bad


def language_of(text):
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    words = set(re.findall(r"[\w']+", text.lower()))
    hits = {lang: len(words & sw) for lang, sw in STOPWORDS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] > 0 else "other"


def predict(text, aspects, B=None):
    """Trả về dict cùng dạng với đầu ra của LLM."""
    B = {**DEFAULTS, **(B or {})}
    text = text.replace("\u2019", "'")                  # nháy cong ’ -> nháy thẳng: VADER chỉ nhận ra phủ định như wasn't với nháy thẳng
    good, bad = aspects_of(text, aspects, B)
    return {"sentiment": sentiment_of(text, B), "language": language_of(text), "aspects_positive": good, "aspects_negative": bad}


def run(cfg, limit=None):
    from src.llm import source_reviews, to_rows
    B = {**DEFAULTS, **cfg.get("baseline", {})}
    assert B["default"] in cfg["llm"]["allowed_sentiments"] and 0 < B["thr"] < 1 and 0 < B["mixed_min"] < 1, "tham số baseline không hợp lệ"
    src = source_reviews(cfg, limit)
    snap = cfg["snapshots"][cfg["kpi"]["llm_snapshot_index"]]
    outs = [predict(t, cfg["llm"]["aspects"], B) for t in src["comment_text"]]
    df = to_rows(cfg, snap, src, outs, provider="baseline", model="vader")
    path = ensure_dir(folder(cfg, "processed")) / "baseline_predictions.csv.gz"
    df.to_csv(path, index=False)
    log.info("Baseline VADER: %d review -> %s (%s)", len(df), path.name, df["sentiment"].value_counts().to_dict())


def self_test():
    asp = {"cleanliness": {"keywords": ["clean", "dirty"]}, "host_friendliness": {"keywords": ["host"]},
           "noise": {"keywords": ["noisy", "noise"]}, "location": {"keywords": ["location"]}}
    s = lambda t: predict(t, asp)["sentiment"]
    assert s("Great place, very clean and lovely host. Highly recommend!") == "positive"
    assert s("Terrible. The room was dirty and awful, never again.") == "negative"
    assert s("Great location and friendly host. The bathroom was filthy and disgusting.") == "mixed"
    assert s("xyz") == DEFAULTS["default"] and s("not clean at all") == "negative"
    assert s("The room wasn't clean.") == s("The room wasn\u2019t clean.") == "negative"     # nháy cong cũng nhận ra phủ định
    p = predict("The host was great but the room was dirty and noisy.", asp)
    assert p["aspects_positive"] == ["host_friendliness"] and set(p["aspects_negative"]) == {"cleanliness", "noise"}, p
    assert predict("El lugar estaba muy limpio y la ubicación excelente para nosotros", asp)["language"] == "es"
    print("baseline.py self-test OK")


if __name__ == "__main__":
    self_test()
