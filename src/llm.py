"""Phân tích review bằng LLM: cảm xúc, khía cạnh khen/chê, ngôn ngữ -> dữ liệu có cấu trúc (JSON).

- Khoá API đọc từ biến môi trường (tên trong cấu hình, mặc định GEMINI_API_KEY); KHÔNG ghi khoá vào mã.
- Có cache (JSONL): chạy lại không gọi lại những review đã xử lý.
- --skip-llm: không gọi API, chỉ dựng kết quả từ cache.
- provider "mock": chạy thử không cần khoá (dùng baseline), CHỈ để kiểm tra quy trình.
"""
from __future__ import annotations

import json
import os
import re
import time

import pandas as pd

from src.utils import ensure_dir, folder, get_logger, load_dotenv, table_file

log = get_logger("llm")


# ---------- chọn mẫu ----------
def select_sample(cfg, limit=None):
    last = cfg["snapshots"][-1]
    R = pd.read_csv(table_file(cfg, "processed", last, "reviews"), low_memory=False)
    R["comment_clean"] = R["comment_clean"].fillna("").astype(str)
    R = R[R["comment_clean"].str.len() > 0].copy()
    flagged = R["mau_llm"].fillna(False).astype(bool) if "mau_llm" in R.columns else pd.Series(False, index=R.index)
    if flagged.any():
        sample = R[flagged]
    else:
        n = min(len(R), cfg["llm"]["sample_size"])
        sample = R.sample(n, random_state=cfg.get("seed", 42))
    sample = sample.sort_values("id")
    return sample.head(limit) if limit else sample


# ---------- cache ----------
def load_cache(path, provider, model):
    """Chỉ nhận kết quả do ĐÚNG provider/model hiện tại tạo ra (tránh lẫn kết quả mock với LLM thật)."""
    cache = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rec = json.loads(line)
                    if rec.get("provider") == provider and rec.get("model") == model:
                        cache[int(rec["review_id"])] = rec
    return cache


def append_cache(path, records):
    with open(path, "a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ---------- nhà cung cấp ----------
class MockAnnotator:
    """Chạy thử không cần khoá: dùng lại baseline. Kết quả KHÔNG phải của LLM."""

    def __init__(self, cfg):
        self.kw = cfg["llm"]["aspects"]

    def annotate(self, texts):
        from src.baseline import predict
        return [predict(t, self.kw) for t in texts]


class GeminiAnnotator:
    def __init__(self, cfg):
        env = cfg["llm"].get("api_key_env", "GEMINI_API_KEY")
        key = os.environ.get(env)
        if not key:
            raise SystemExit(f"Thiếu khoá API: hãy đặt biến môi trường {env} (xem .env.example).")
        from google import genai
        from google.genai import types
        self.client = genai.Client(api_key=key)
        self.types = types
        self.model = cfg["llm"]["model"]
        self.aspects = list(cfg["llm"]["aspects"].keys())
        self.max_chars = cfg["llm"].get("max_chars_per_review", 1200)

    def _prompt(self, texts):
        items = [{"id": str(i + 1), "text": t[: self.max_chars]} for i, t in enumerate(texts)]
        return (
            "You analyse Airbnb guest reviews. For EACH review return one JSON object with keys:\n"
            '"id" (copy the given id), '
            '"sentiment" (exactly one of: positive, mixed, negative), '
            f'"aspects_positive" (list; only values from {self.aspects}), '
            f'"aspects_negative" (list; only values from {self.aspects}), '
            '"language" (ISO 639-1 code of the review text, e.g. en, es, fr).\n'
            "Rules: judge only what the review says; use mixed only when it clearly contains both praise and complaints; "
            "aspects are the topics explicitly praised or criticised. "
            "Return ONLY a JSON array with one object per review, in the same order, no commentary.\n\n"
            "Reviews:\n" + json.dumps(items, ensure_ascii=False)
        )

    def annotate(self, texts):
        config = self.types.GenerateContentConfig(temperature=0, response_mime_type="application/json")
        resp = self.client.models.generate_content(model=self.model, contents=self._prompt(texts), config=config)
        data = json.loads(re.sub(r"^```(?:json)?|```$", "", resp.text.strip(), flags=re.M).strip())
        if not isinstance(data, list) or len(data) != len(texts):
            raise ValueError("Số phần tử trả về không khớp số review gửi đi")
        by_id = {str(d.get("id")): d for d in data}
        return [by_id[str(i + 1)] for i in range(len(texts))]  # ghép lại theo id cục bộ 1..n


def make_annotator(cfg):
    provider = cfg["llm"]["provider"]
    if provider == "mock":
        log.warning("provider=mock: kết quả lấy từ baseline, KHÔNG phải LLM thật")
        return MockAnnotator(cfg)
    if provider == "gemini":
        return GeminiAnnotator(cfg)
    raise SystemExit(f"provider không hỗ trợ: {provider}")


def clean_record(raw, allowed_sent, aspects):
    """Kiểm tra đầu ra của LLM: giá trị lạ -> None / bỏ khỏi danh sách."""
    sent = str(raw.get("sentiment", "")).strip().lower()
    return {
        "sentiment": sent if sent in allowed_sent else None,
        "aspects_positive": [a for a in raw.get("aspects_positive", []) if a in aspects],
        "aspects_negative": [a for a in raw.get("aspects_negative", []) if a in aspects],
        "language": str(raw.get("language", "")).strip().lower()[:3] or None,
    }


def run(cfg, skip_llm=False, limit=None):
    load_dotenv()
    lc = cfg["llm"]
    sample = select_sample(cfg, limit=limit)
    cache_path = lc["cache"]
    ensure_dir(os.path.dirname(cache_path) or ".")
    provider = lc["provider"]
    model = lc.get("model", "") if provider != "mock" else "mock"
    cache = load_cache(cache_path, provider, model)
    todo = sample[~sample["id"].isin(cache.keys())]
    log.info("Mẫu LLM: %d review (%d đã có trong cache, %d cần gọi)", len(sample), len(sample) - len(todo), len(todo))

    if len(todo) and not skip_llm:
        annotator = make_annotator(cfg)
        bs, aspects = lc["batch_size"], set(lc["aspects"].keys())
        pause = 60.0 / lc["requests_per_minute"] if lc["provider"] == "gemini" else 0
        for start in range(0, len(todo), bs):
            batch = todo.iloc[start:start + bs]
            for attempt in range(1, lc["max_retries"] + 1):
                try:
                    outs = annotator.annotate(batch["comment_clean"].tolist())
                    recs = []
                    for rid, lid, out in zip(batch["id"], batch["listing_id"], outs):
                        recs.append({"review_id": int(rid), "listing_id": int(lid), "provider": provider, "model": model,
                                     **clean_record(out, set(lc["allowed_sentiments"]), aspects)})
                    append_cache(cache_path, recs)
                    cache.update({r["review_id"]: r for r in recs})
                    break
                except SystemExit:
                    raise
                except Exception as e:  # 429, mạng, JSON sai...
                    wait = min(60, 2 ** attempt * 2)
                    log.warning("Lô %d lỗi (lần %d/%d): %s -> chờ %ss", start // bs, attempt, lc["max_retries"], e, wait)
                    time.sleep(wait)
            else:
                log.error("Bỏ qua lô %d sau %d lần thử (chạy lại sẽ thử tiếp)", start // bs, lc["max_retries"])
            time.sleep(pause)
    elif len(todo):
        log.warning("--skip-llm: còn %d review chưa có kết quả", len(todo))

    rows = []
    for rid in sample["id"]:
        rec = cache.get(int(rid))
        if rec:
            rows.append({**rec, "aspects_positive": "|".join(rec["aspects_positive"]),
                         "aspects_negative": "|".join(rec["aspects_negative"])})
    out = ensure_dir(folder(cfg, "processed")) / "llm_results.csv"
    pd.DataFrame(rows, columns=["review_id", "listing_id", "sentiment", "aspects_positive",
                                "aspects_negative", "language"]).to_csv(out, index=False)
    log.info("Kết quả LLM: %d/%d review -> %s", len(rows), len(sample), out)
