"""Tải dữ liệu Inside Airbnb vào data/raw, chỉ những bảng x mốc mà KPI cần (xem utils.tables_snapshots).

Chạy:  python -m src.download --config configs/new_york_city.yaml
Ra:    data/raw/<mốc>/<bảng>.csv.gz   (việc lọc theo ID của nhóm làm ở qa.py, đọc theo khối)
"""
import gzip
import shutil
import time
import urllib.request

from src.utils import cli, ensure_dir, get_logger, raw_file, tables_snapshots

log = get_logger("download")
TIMEOUT, RETRIES, BACKOFF = 60, 3, 2.0


def is_valid(path):
    """Tệp tồn tại, không rỗng và gzip đọc hết được (tệp tải thiếu sẽ lỗi ở đây)."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except (OSError, EOFError):
        return False


def fetch(url, dest):
    """Bỏ qua nếu tệp đã hợp lệ; lỗi gì cũng thử lại tối đa RETRIES lần."""
    if is_valid(dest):
        log.info("[skip] %s", dest)
        return True
    ensure_dir(dest.parent)
    part = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
            part.replace(dest)
            if not is_valid(dest):
                raise ValueError("gzip hỏng")
            log.info("[ok]   %s", dest)
            return True
        except Exception as e:
            log.warning("[fail] %s (lần %d/%d): %s", url, attempt + 1, RETRIES, e)
            part.unlink(missing_ok=True)
            dest.unlink(missing_ok=True)
            time.sleep(BACKOFF * 2 ** attempt)
    return False


def main(cfg):
    base = cfg.get("base_url", "https://data.insideairbnb.com").rstrip("/")
    root = cfg["data_root"].strip("/")
    tables = ("listings", "calendar", "reviews")
    failed = [f"{base}/{root}/{snap}/data/{table}.csv.gz"
              for snap in cfg["snapshots"] for table in tables
              if not fetch(f"{base}/{root}/{snap}/data/{table}.csv.gz", raw_file(snap, table))]
    if failed:
        raise SystemExit("Tải thất bại:\n" + "\n".join(failed))


if __name__ == "__main__":
    cli(main)
