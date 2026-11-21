"""Hàm dùng chung: cấu hình, đường dẫn, đọc tệp, log, dòng lệnh."""
from __future__ import annotations

import argparse
import hashlib
import logging
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]          # thư mục gốc project: chạy từ đâu cũng đúng đường dẫn
RAW, PROC = ROOT / "data" / "raw", ROOT / "data" / "processed"
REPORTS, FIGURES = ROOT / "reports", ROOT / "figures"
ID_COLUMNS = ["id", "listing_id", "review_id", "assigned_listing_id"]
BOOL_COLUMNS = ["has_wifi", "has_kitchen", "is_superhost"]   # True / False / NA (NA = chưa xác định)


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # YAML hay đọc 2025-09-01 (không có nháy) thành kiểu ngày -> ép về chuỗi
    cfg["snapshots"] = [str(s) for s in cfg["snapshots"]]
    cfg["_dir"] = Path(path).resolve().parent             # thư mục chứa YAML (đường dẫn assignments tính từ đây)
    return cfg


def snapshot_of(cfg, key):
    """Mốc dùng cho một KPI, chọn theo chỉ số trong config (vd. kpi1_snapshot_index: 0)."""
    return cfg["snapshots"][cfg["kpi"][key]]


def tables_snapshots(cfg):
    """Bảng nào cần ở mốc nào: listings ở mọi mốc; calendar chỉ mốc KPI 3; reviews chỉ mốc LLM."""
    return {
        "listings": cfg["snapshots"],
        "calendar": [snapshot_of(cfg, "kpi3_snapshot_index")],
        "reviews": [snapshot_of(cfg, "llm_snapshot_index")],
    }


def raw_file(snap, table):
    return RAW / snap / f"{table}.csv.gz"


def clean_file(snap, table):
    return PROC / snap / f"{table}_clean.csv.gz"


def ensure_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path, **kw):
    """Đọc MỌI cột là chuỗi nguyên văn: không làm tròn ID dài 19 chữ số, không biến 'N/A' thành NaN (QA tự phân loại)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kw)


def read_clean(path, **kw):
    """Đọc tệp sạch: ID giữ dạng chuỗi, cột T/F/NA đọc thành boolean (có NA), các cột còn lại pandas tự đoán kiểu."""
    dtype = {c: str for c in ID_COLUMNS} | {c: "boolean" for c in BOOL_COLUMNS}
    return pd.read_csv(path, dtype=dtype, low_memory=False, **kw)


def pct1(n, d):
    """Phần trăm n/d cho số đơn; d = 0 -> NaN (không bao giờ ghi 0%)."""
    return n / d * 100 if d > 0 else np.nan


def pct(n, d):
    """Phần trăm n/d cho cả cột; d = 0 -> NaN."""
    return n / d.where(d > 0) * 100


def text_hash(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def get_logger(name):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return logging.getLogger(name)


def cli(main):
    """Chạy một mô-đun từ dòng lệnh: python -m src.<tên> --config X.yaml [--co-nao]; cờ --a-b thành tham số a_b=True của main."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    args, flags = ap.parse_known_args()
    main(load_config(args.config), **{f[2:].replace("-", "_"): True for f in flags})
