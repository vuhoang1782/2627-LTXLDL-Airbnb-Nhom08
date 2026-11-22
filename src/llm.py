"""Phân tích review bằng LLM (Gemini): cảm xúc, khía cạnh khen/chê, ngôn ngữ -> bảng có cấu trúc.

- Khoá API đọc từ biến môi trường (tên trong config, mặc định GEMINI_API_KEY); KHÔNG ghi khoá vào mã.
- Có cache (JSONL): chạy lại không gọi lại review đã xử lý. --skip-llm: chỉ dùng cache, không gọi API.
Đầu ra: data/processed/llm_predictions.csv.gz  (mỗi aspect có 2 cột <aspect>_positive / <aspect>_negative: 1 hoặc ô trống)
"""
from __future__ import annotations

import json
import os
import re
import time

import pandas as pd

from src.qa import text_hash
from src.utils import ensure_dir, folder, get_logger, load_dotenv, read_clean, snapshot_of, table_file

log = get_logger("llm")


def columns(aspects):
    base = ["snapshot", "review_id", "listing_id", "text_hash", "provider", "model", "status", "sentiment", "language"]
    return base + [f"{a}_{s}" for a in aspects for s in ("positive", "negative")]


def source_reviews(cfg, limit=None):
    """Review cần phân tích: những review đã qua QA09 (llm_source_eligible)."""
    snap = snapshot_of(cfg, "llm_snapshot_index")
    R = read_clean(table_file(cfg, "processed", snap, "reviews_clean"))
    R = R[R["llm_source_eligible"]].sort_values("id")
    return R.head(limit) if limit else R


def to_rows(cfg, snap, src, outs, provider, model):
    """Ghép đầu ra (dict) của LLM/baseline thành các dòng có cột chuẩn."""
    aspects, rows = list(cfg["llm"]["aspects"]), []
    for (_, r), o in zip(src.iterrows(), outs):
        row = {"snapshot": snap, "review_id": r["id"], "listing_id": r["listing_id"], "text_hash": text_hash(r["comment_text"]),
               "provider": provider, "model": model, "status": "ok",
               "sentiment": str(o.get("sentiment", "")).strip().lower(), "language": str(o.get("language", "")).strip().lower()}
        for a in aspects:
            row[f"{a}_positive"] = 1 if a in o.get("aspects_positive", []) else ""
            row[f"{a}_negative"] = 1 if a in o.get("aspects_negative", []) else ""
        rows.append(row)
    return pd.DataFrame(rows, columns=columns(aspects))


# ---------------------------------------------------------------- nhà cung cấp
class GeminiAnnotator:
    def __init__(self, cfg):
        env = cfg["llm"].get("api_key_env", "GEMINI_API_KEY")
        key = os.environ.get(env)
        if not key:
            raise SystemExit(f"Thiếu khoá API: hãy đặt biến môi trường {env} (xem .env.example).")
        from google import genai
        from google.genai import types
        self.client, self.types = genai.Client(api_key=key), types
        self.model, self.aspects = cfg["llm"]["model"], cfg["llm"]["aspects"]
        self.max_chars = cfg["llm"].get("max_chars_per_review", 1200)

    def prompt(self, texts):
        defs = "\n".join(f"- {code}: {a['description']}" for code, a in self.aspects.items())
        items = [{"id": str(i + 1), "text": t[: self.max_chars]} for i, t in enumerate(texts)]
        return (
            "You analyse Airbnb guest reviews. For EACH review return one JSON object with keys:\n"
            '"id" (copy the given id), "sentiment", "language", "aspects_positive", "aspects_negative".\n'
            "- sentiment: exactly one of positive, negative, mixed. positive = overall satisfied, no significant complaint; "
            "negative = negative experience dominates; mixed = significant praise AND significant complaints.\n"
            "- language: ISO 639-1 code of the review text (en, es, fr...).\n"
            f"- aspects (use ONLY these codes):\n{defs}\n"
            "- aspects_positive: codes the review clearly praises. aspects_negative: codes the review clearly complains about. "
            "An aspect both praised and criticised goes in both lists. Do not list an aspect that is only mentioned neutrally "
            "or not mentioned. Judge each aspect independently of the overall sentiment. "
            "amenities needs a SPECIFIC facility with a good/bad comment ('Great apartment' or 'Great amenities' -> none); "
            "'the bathroom was dirty' is cleanliness, 'the shower was broken' is amenities.\n"
            "Return ONLY a JSON array, one object per review, same order, no commentary.\n\nReviews:\n" + json.dumps(items, ensure_ascii=False))

    def annotate(self, texts):
        cfg = self.types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        resp = self.client.models.generate_content(model=self.model, contents=self.prompt(texts), config=cfg)
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", resp.text.strip(), flags=re.M).strip())
        by_id = {str(d.get("id")): d for d in data}
        if len(by_id) != len(texts) or any(str(i + 1) not in by_id for i in range(len(texts))):
            raise ValueError("Số phần tử trả về không khớp số review gửi đi")
        return [by_id[str(i + 1)] for i in range(len(texts))]


# ---------------------------------------------------------------- chạy
def load_cache(path):
    cache = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if line.strip():
                rec = json.loads(line)
                cache[(rec["review_id"], rec["text_hash"], rec["provider"], rec["model"])] = rec
    return cache


def run(cfg, skip_llm=False, limit=None):
    load_dotenv()
    lc, snap = cfg["llm"], snapshot_of(cfg, "llm_snapshot_index")
    provider = lc["provider"]
    if provider != "gemini":
        raise SystemExit(f"provider không hỗ trợ: {provider}; chỉ hỗ trợ gemini")
    model = lc["model"]
    src = source_reviews(cfg, limit)
    cache_path = lc["cache"]
    ensure_dir(os.path.dirname(cache_path) or ".")
    cache = load_cache(cache_path)
    key = lambda r: (r["id"], text_hash(r["comment_text"]), provider, model)
    todo = src[[key(r) not in cache for _, r in src.iterrows()]]
    log.info("Review cần phân tích: %d (đã có trong cache: %d, cần gọi: %d)", len(src), len(src) - len(todo), len(todo))

    if len(todo) and skip_llm:
        log.warning("--skip-llm: còn %d review chưa có kết quả", len(todo))
    elif len(todo):
        annotator, bs = GeminiAnnotator(cfg), lc["batch_size"]
        pause = 60.0 / lc["requests_per_minute"]
        for start in range(0, len(todo), bs):
            batch = todo.iloc[start:start + bs]
            for attempt in range(1, lc["max_retries"] + 1):
                try:
                    outs = annotator.annotate(batch["comment_text"].tolist())
                    df = to_rows(cfg, snap, batch, outs, provider, model)
                    with open(cache_path, "a", encoding="utf-8") as f:
                        for rec in df.to_dict("records"):
                            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            cache[(rec["review_id"], rec["text_hash"], provider, model)] = rec
                    break
                except SystemExit:
                    raise
                except Exception as e:                       # 429, mạng, JSON sai...
                    wait = min(60, 2 ** attempt * 2)
                    log.warning("Lô %d lỗi (lần %d/%d): %s -> chờ %ss", start // bs, attempt, lc["max_retries"], e, wait)
                    time.sleep(wait)
            else:
                log.error("Bỏ qua lô %d sau %d lần thử (chạy lại sẽ thử tiếp)", start // bs, lc["max_retries"])
            time.sleep(pause)

    rows = [cache[key(r)] for _, r in src.iterrows() if key(r) in cache]
    out = ensure_dir(folder(cfg, "processed")) / "llm_predictions.csv.gz"
    pd.DataFrame(rows, columns=columns(list(lc["aspects"]))).to_csv(out, index=False)
    log.info("Kết quả LLM: %d/%d review -> %s", len(rows), len(src), out)
