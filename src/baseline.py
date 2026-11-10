"""Phương pháp đối chứng KHÔNG dùng LLM: từ điển cảm xúc + từ khoá khía cạnh + đoán ngôn ngữ bằng từ dừng.

Đây là baseline đơn giản (chủ yếu tiếng Anh). Nó sai nhiều với review ngôn ngữ khác; đó là một phần của phân tích lỗi.
"""
from __future__ import annotations

import re

import pandas as pd

from src.utils import ensure_dir, folder, get_logger

log = get_logger("baseline")

POSITIVE = set("""great amazing perfect clean comfortable lovely wonderful excellent recommend recommended love loved
best nice friendly helpful spotless beautiful cozy convenient fantastic awesome superb pleasant lovely quiet cosy
spacious welcoming responsive gem stunning charming delightful safe easy fast comfy""".split())
NEGATIVE = set("""dirty noisy rude terrible awful bad worst smell smelly broken uncomfortable small cockroach cockroaches
bugs bug roaches disappointing disappointed unsafe cold filthy loud disgusting horrible poor misleading scam mold
moldy stain stained overpriced unresponsive cancelled canceled problem problems issue issues unhelpful sketchy""".split())
NEGATIONS = {"not", "no", "never", "n't", "isn't", "wasn't", "don't", "didn't", "wouldn't", "without"}

STOPWORDS = {
    "en": set("the and was is were very with for you our this that had have but great place stay".split()),
    "es": set("el la los las y fue muy con para una un que estuvo lugar excelente nos muy".split()),
    "fr": set("le la les et était très avec pour une un que nous appartement séjour très".split()),
    "de": set("der die das und war sehr mit für ein eine wir wohnung aufenthalt nicht".split()),
    "pt": set("o a os as e foi muito com para um uma que nós apartamento estadia não".split()),
    "it": set("il lo la gli le e era molto con per un una che noi appartamento soggiorno non".split()),
}


def tokens(text):
    return re.findall(r"[\w']+", text.lower())


def detect_language(text):
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    toks = set(tokens(text))
    scores = {lang: len(toks & words) for lang, words in STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "other"


def _score(sentence_tokens):
    pos = neg = 0
    for i, tok in enumerate(sentence_tokens):
        negated = any(t in NEGATIONS for t in sentence_tokens[max(0, i - 2):i])
        if tok in POSITIVE:
            neg, pos = (neg + 1, pos) if negated else (neg, pos + 1)
        elif tok in NEGATIVE:
            pos, neg = (pos + 1, neg) if negated else (pos, neg + 1)
    return pos, neg


def label(pos, neg):
    if pos and neg and abs(pos - neg) <= 1:
        return "mixed"
    if neg > pos:
        return "negative"
    return "positive"  # mặc định positive vì đa số review Airbnb tích cực (lớp đa số)


def predict(text, aspect_keywords):
    pos, neg = _score(tokens(text))
    asp_pos, asp_neg = set(), set()
    for sentence in re.split(r"[.!?\n]+", text):
        toks = tokens(sentence)
        if not toks:
            continue
        s_pos, s_neg = _score(toks)
        for aspect, words in aspect_keywords.items():
            if any(w in sentence.lower() for w in words):
                if s_neg > s_pos:
                    asp_neg.add(aspect)
                elif s_pos > s_neg:
                    asp_pos.add(aspect)
    return {
        "sentiment": label(pos, neg),
        "aspects_positive": sorted(asp_pos),
        "aspects_negative": sorted(asp_neg),
        "language": detect_language(text),
    }


def run(cfg, limit=None):
    from src.llm import select_sample  # cùng mẫu với LLM để so sánh công bằng
    sample = select_sample(cfg, limit=limit)
    kw = cfg["llm"]["aspects"]
    rows = []
    for rid, lid, text in zip(sample["id"], sample["listing_id"], sample["comment_clean"]):
        p = predict(text, kw)
        rows.append({"review_id": rid, "listing_id": lid, "sentiment": p["sentiment"],
                     "aspects_positive": "|".join(p["aspects_positive"]),
                     "aspects_negative": "|".join(p["aspects_negative"]), "language": p["language"]})
    out = ensure_dir(folder(cfg, "processed")) / "baseline_results.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    log.info("Baseline: %d review -> %s", len(rows), out)
