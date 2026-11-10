"""Bước 1: tải 4 mốc x 3 tệp từ Inside Airbnb, kiểm tệp tồn tại, gzip nguyên vẹn, có cột khoá."""
from __future__ import annotations

import gzip
import shutil
import time
import urllib.error
import urllib.request

import pandas as pd

from src.utils import TABLES, ensure_dir, folder, get_logger, table_file

log = get_logger("download")

# Cột khoá tối thiểu mỗi bảng phải có (không bắt buộc price: một số mốc không có).
REQUIRED_COLUMNS = {
    "listings": ["id"],
    "calendar": ["listing_id", "date", "available"],
    "reviews": ["listing_id", "id", "date"],
}
HEADERS = {"User-Agent": "Mozilla/5.0 (UET.DSE2049 student project)"}
OK_STATUS = {"downloaded", "exists"}


def url_for(cfg, snap, table):
    base = cfg["base_url"].rstrip("/")
    root = cfg["data_root"].strip("/")
    return f"{base}/{root}/{snap}/data/{table}.csv.gz"


def _verify_gzip(path):
    """Đọc hết tệp gzip để bắt lỗi tải dở (CRC sai / thiếu byte)."""
    with gzip.open(path, "rb") as f:
        while f.read(1 << 24):
            pass


def _missing_columns(path, table):
    cols = set(pd.read_csv(path, nrows=0).columns)
    return [c for c in REQUIRED_COLUMNS[table] if c not in cols]


def _download(url, dest, retries=3):
    tmp = dest.with_name(dest.name + ".part")
    status = "error"
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
                shutil.copyfileobj(resp, out, 1 << 20)
            _verify_gzip(tmp)
            tmp.replace(dest)
            return "downloaded"
        except urllib.error.HTTPError as e:
            status = f"http_{e.code}"
            if e.code in (403, 404):  # thử lại cũng vô ích
                break
        except Exception as e:  # lỗi mạng, gzip hỏng...
            status = f"error_{type(e).__name__}"
        time.sleep(2 * attempt)
    tmp.unlink(missing_ok=True)
    return status


def run(cfg, strict=True):
    rows = []
    for snap in cfg["snapshots"]:
        ensure_dir(folder(cfg, "raw", snap))
        for table in TABLES:
            dest = table_file(cfg, "raw", snap, table)
            url = url_for(cfg, snap, table)
            if dest.exists() and dest.stat().st_size > 0:
                status = "exists"
            else:
                log.info("Tải %s / %s", snap, table)
                status = _download(url, dest)
            if status in OK_STATUS:
                try:
                    missing = _missing_columns(dest, table)
                except Exception as e:
                    status, missing = f"unreadable_{type(e).__name__}", []
                if missing:
                    status = "missing_key_columns:" + ",".join(missing)
            rows.append({
                "snapshot": snap,
                "table": table,
                "status": status,
                "bytes": dest.stat().st_size if dest.exists() else 0,
                "url": url,
            })
    result = pd.DataFrame(rows)
    out = ensure_dir(cfg["paths"]["reports"]) / "download_log.csv"
    result.to_csv(out, index=False)
    bad = result[~result["status"].isin(OK_STATUS)]
    if len(bad):
        log.error("Có %d tệp lỗi:\n%s", len(bad), bad[["snapshot", "table", "status"]].to_string(index=False))
        if strict:
            raise SystemExit("Tải dữ liệu chưa đủ. Xem reports/download_log.csv")
    log.info("Tải xong: %d tệp hợp lệ", len(result) - len(bad))
    return result
