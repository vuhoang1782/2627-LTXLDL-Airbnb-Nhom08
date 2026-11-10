"""Tiện ích dùng chung: đọc cấu hình, đường dẫn, log, đọc tệp .env."""
from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

TABLES = ("listings", "calendar", "reviews")


def load_config(path):
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # YAML đọc 2025-09-01 (không có nháy) thành kiểu ngày -> ép về chuỗi cho chắc.
    cfg["snapshots"] = [str(s) for s in cfg["snapshots"]]
    return cfg


def folder(cfg, kind, snap=None):
    """Thư mục theo loại (raw / interim / processed / ...) và mốc."""
    p = Path(cfg["paths"][kind])
    return p / snap if snap else p


def table_file(cfg, kind, snap, table):
    return folder(cfg, kind, snap) / f"{table}.csv.gz"


def ensure_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_logger(name):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger(name)


def load_dotenv(path=".env"):
    """Đọc .env đơn giản (KEY=VALUE) vào biến môi trường; không ghi đè biến đã có."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def price_col(cfg):
    """Tên cột giá đã làm sạch, theo tiền tệ trong cấu hình (vd. price_usd)."""
    return f"price_{cfg['currency'].lower()}"
