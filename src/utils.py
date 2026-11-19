"""Hàm dùng chung: đọc cấu hình, đường dẫn, đọc tệp, log, .env."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]          # thư mục gốc project: chạy từ đâu cũng đúng đường dẫn
TABLES = ("listings", "calendar", "reviews")
ID_COLUMNS = ["id", "listing_id", "review_id", "assigned_listing_id"]


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
    """Bảng nào cần xử lý ở mốc nào: listings ở mọi mốc; calendar chỉ mốc KPI 3; reviews chỉ mốc LLM."""
    return {
        "listings": cfg["snapshots"],
        "calendar": [snapshot_of(cfg, "kpi3_snapshot_index")],
        "reviews": [snapshot_of(cfg, "llm_snapshot_index")],
    }


def folder(cfg, kind, snap=None):
    p = ROOT / cfg.get("paths", {}).get(kind, f"data/{kind}")
    return p / snap if snap else p


def table_file(cfg, kind, snap, name):
    """vd. table_file(cfg, 'raw', '2025-09-01', 'listings') -> data/raw/2025-09-01/listings.csv.gz"""
    return folder(cfg, kind, snap) / f"{name}.csv.gz"


def ensure_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_text(path, **kw):
    """Đọc MỌI cột là chuỗi nguyên văn: không làm tròn ID dài 19 chữ số, không biến 'N/A' thành NaN (QA tự phân loại)."""
    return pd.read_csv(path, dtype=str, keep_default_na=False, **kw)


def read_clean(path, **kw):
    """Đọc tệp sạch: ID giữ dạng chuỗi, các cột còn lại pandas tự đoán kiểu."""
    return pd.read_csv(path, dtype={c: str for c in ID_COLUMNS}, low_memory=False, **kw)


def get_logger(name):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return logging.getLogger(name)


def load_dotenv(path=".env"):
    """Đọc .env đơn giản (KEY=VALUE) vào biến môi trường; không ghi đè biến đã có."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
