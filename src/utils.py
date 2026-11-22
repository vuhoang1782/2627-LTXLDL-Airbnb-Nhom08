"""Hàm dùng chung: đọc cấu hình, đường dẫn, đọc tệp, log, .env."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
    validate_amenities_config(cfg)
    return cfg


def validate_amenities_config(cfg):
    """Kiểm tra tiêu chí KPI 2 trước khi pipeline ghi bất kỳ đầu ra nào."""
    rules = cfg.get("qa", {}).get("amenity_rules")
    if not isinstance(rules, dict) or not rules:
        raise ValueError("qa.amenity_rules phải là danh mục quy tắc tiện nghi không rỗng")
    for key, rule in rules.items():
        where = f"qa.amenity_rules.{key}"
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", key):
            raise ValueError(f"{where}: khóa phải dùng chữ thường, số và dấu gạch dưới")
        if not isinstance(rule, dict) or set(rule) - {"label", "exact", "patterns"}:
            raise ValueError(f"{where}: chỉ dùng label, exact và patterns")
        if not isinstance(rule.get("label"), str) or not rule["label"].strip():
            raise ValueError(f"{where}.label phải là tên hiển thị không rỗng")
        for field in ("exact", "patterns"):
            values = rule.get(field, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{where}.{field} phải là danh sách các chuỗi không rỗng")
        if not rule.get("exact") and not rule.get("patterns"):
            raise ValueError(f"{where}: cần ít nhất một tên exact hoặc mẫu patterns")
        for pattern in rule.get("patterns", []):
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                raise ValueError(f"{where}.patterns: regex không hợp lệ: {e}") from e

    selected = cfg.get("kpi", {}).get("kpi2_required_amenities")
    if not isinstance(selected, list) or not selected or any(not isinstance(k, str) for k in selected):
        raise ValueError("kpi.kpi2_required_amenities phải là danh sách khóa tiện nghi không rỗng")
    if len(selected) != len(set(selected)):
        raise ValueError("kpi.kpi2_required_amenities có tiêu chí trùng")
    unknown = [key for key in selected if key not in rules]
    if unknown:
        raise ValueError(f"kpi.kpi2_required_amenities: chưa định nghĩa {', '.join(unknown)} trong qa.amenity_rules")


def amenity_rules_hash(cfg):
    """Dấu quy tắc nhận diện để không tính KPI bằng cờ QA từ bộ quy tắc cũ."""
    rules = {
        key: {"exact": sorted(v.strip().lower() for v in rule.get("exact", [])),
              "patterns": sorted(rule.get("patterns", []))}
        for key, rule in cfg["qa"]["amenity_rules"].items()
    }
    return hashlib.sha256(json.dumps(rules, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def kpi2_metadata(cfg):
    """Lưu bộ tiêu chí và nhãn cùng số liệu; biểu đồ đọc chính metadata này."""
    keys = cfg["kpi"]["kpi2_required_amenities"]
    return {
        "required_amenities": json.dumps(keys, ensure_ascii=False),
        "amenities_label": " + ".join(cfg["qa"]["amenity_rules"][key]["label"].strip() for key in keys),
    }


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
