"""Tải dữ liệu Inside Airbnb theo config và kiểm tra tính toàn vẹn."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yaml

BASE_URL = "https://data.insideairbnb.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (LTXLDL student project)"}

FILES = {
    "listings": {
        "rel": "data/listings.csv.gz",
        "required": ["id", "price", "neighbourhood_cleansed", "latitude",
                     "longitude", "room_type", "minimum_nights", "last_scraped"],
    },
    "calendar": {
        "rel": "data/calendar.csv.gz",
        "required": ["listing_id", "date", "available", "minimum_nights"], # trước 2 file 2025 phần calendar tồn tại khóa, nhưng sau năm 2026 thì không, 2 cột prices đó đều rỗng, nhưng file listing ở ngày 1/9/2025, và các 2026 listing đêu có prices, nên chắc ko cần
    },
    "reviews": {
        "rel": "data/reviews.csv.gz",
        "required": ["listing_id", "id", "date", "comments"],
    },
    "neighbourhoods": {
        "rel": "visualisations/neighbourhoods.geojson",
        "required": [],
    },
}

log = logging.getLogger("download")

class DownloadError(Exception):
    def __init__(self, status, url):
        super().__init__(f"HTTP {status}: {url}")
        self.status = status

def download_file(url: str, dest: Path, retries: int = 3, timeout: int = 60) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(1, retries + 1):
        try:
            with requests.get(url, stream=True, timeout=timeout, headers=HEADERS) as r:
                if r.status_code >= 400:
                    raise DownloadError(r.status_code, url)
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.replace(dest)
            return
        except DownloadError as e:
            tmp.unlink(missing_ok=True)
            if e.status < 500 or attempt == retries:   # 403/404 không thử lại
                raise
            time.sleep(2 ** attempt)
        except requests.RequestException:
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
# ========================================================================

def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["snapshots"] = [str(s) for s in cfg["snapshots"]]  
    return cfg


def build_url(data_root: str, snapshot: str, rel: str) -> str:
    return f"{BASE_URL}/{data_root}/{snapshot}/{rel}"


def validate_file(path: Path, kind: str) -> None:
    spec = FILES[kind]
    if path.suffix == ".gz":
        with open(path, "rb") as f:
            if f.read(2) != b"\x1f\x8b":
                raise ValueError("Không phải file gzip")
        with gzip.open(path, "rb") as g:          
            while g.read(1 << 20):
                pass
        cols = set(pd.read_csv(path, nrows=0).columns)
        missing = set(spec["required"]) - cols
        if missing:
            raise ValueError(f"Thiếu cột khoá: {sorted(missing)}")
    else:
        with open(path, encoding="utf-8") as f:
            gj = json.load(f)
        if not gj.get("features"):
            raise ValueError("GeoJSON không có features")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run(config_path: str, force: bool = False) -> int:
    cfg = load_config(config_path)
    raw_root = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]
    manifest = []

    for snap in cfg["snapshots"]:
        for kind, spec in FILES.items():
            dest = raw_root / snap / Path(spec["rel"]).name
            url = build_url(cfg["data_root"], snap, spec["rel"])
            
            # Bổ sung http_status mặc định là None để hàm check đọc được
            row = {"snapshot": snap, "table": kind, "url": url, "path": str(dest),
                   "status": "", "http_status": None, "size_bytes": None, "sha256": None,
                   "downloaded_at": datetime.now(timezone.utc).isoformat(),
                   "message": ""}
            try:
                if dest.exists() and not force:
                    try:
                        validate_file(dest, kind)
                        row["status"] = "skipped"
                    except Exception:
                        log.warning("File cũ hỏng, tải lại: %s", dest)
                        dest.unlink()
                if not row["status"]:
                    log.info("Tải %s", url)
                    download_file(url, dest)
                    validate_file(dest, kind)
                    row["status"] = "ok"
                row["size_bytes"] = dest.stat().st_size
                row["sha256"] = sha256_of(dest)
                
            except DownloadError as e: # Bắt lỗi 403/404/500 từ hàm mới
                row["status"] = "failed"
                row["http_status"] = e.status
                row["message"] = str(e)
                log.error("%s/%s: %s", snap, kind, e)
                
            except Exception as e:     # Bắt các lỗi khác (file hỏng, giải nén lỗi...)
                row["status"], row["message"] = "failed", str(e)
                log.error("%s/%s: %s", snap, kind, e)
                
            manifest.append(row)

    out = Path(cfg.get("reports_dir", "reports")) / "download_manifest.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(manifest).to_csv(out, index=False)

    failed = [m for m in manifest if m["status"] == "failed"]
    log.info("Xong: %d file, %d lỗi. Manifest: %s", len(manifest), len(failed), out)
    return 1 if failed else 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--force", action="store_true", help="tải lại dù file đã có")
    args = ap.parse_args()
    sys.exit(run(args.config, args.force))
