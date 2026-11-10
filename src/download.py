import gzip
import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://data.insideairbnb.com"
FILES = ["listings.csv.gz", "calendar.csv.gz", "reviews.csv.gz"]
TIMEOUT, MAX_RETRIES, BACKOFF = 60, 3, 2.0

def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Ép các mốc snapshot về chuỗi (tránh lỗi YAML tự nhận diện là kiểu date)
    cfg["snapshots"] = [str(s) for s in cfg["snapshots"]]
    return cfg

def is_valid(path: Path) -> bool:
    """Kiểm tra file tồn tại và giải nén được toàn bộ (chống file cụt)."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except (OSError, EOFError):
        return False

def download(url: str, dest: Path) -> str | None:
    """Tải file dùng urllib. Trả về None nếu OK, ngược lại trả về chuỗi lỗi."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    err = None

    for attempt in range(MAX_RETRIES):
        try:
            # Thêm User-Agent để tránh bị server chặn (lỗi 403)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
                # copyfileobj đọc từng khối dữ liệu từ mạng và ghi xuống ổ cứng
                shutil.copyfileobj(r, f)
                
            # Đổi tên file tạm thành file chính thức
            part.replace(dest)
            return None
            
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            # Nếu là lỗi 4xx (trừ 429 Too Many Requests) thì thử lại cũng vô ích -> thoát luôn
            if 400 <= e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            # Bắt các lỗi mất mạng, timeout, hoặc lỗi ghi file (OSError)
            err = f"Network/IO error: {e}"
        finally:
            # Xóa file rác .part nếu tải thất bại
            part.unlink(missing_ok=True)
            
        if attempt < MAX_RETRIES - 1:
            time.sleep(BACKOFF * 2**attempt)   # chờ 2s, 4s trước khi thử lại; lần cuối không chờ
        
    return err

def fetch(url: str, dest: Path) -> bool:
    """Kết hợp kiểm tra file cũ và tải mới."""
    if is_valid(dest):
        print(f"[skip] {dest}")
        return True
        
    err = download(url, dest)
    if err:
        print(f"[fail] {url} -> {err}")
        return False
        
    # Sau khi tải xong, bắt buộc phải kiểm tra lại tính toàn vẹn bằng gzip
    if not is_valid(dest):
        print(f"[fail] {url} -> File tải về bị hỏng (gzip integrity check failed)")
        dest.unlink(missing_ok=True) # Xóa file hỏng đi
        return False
        
    print(f"[ok]   {dest}")
    return True

def download_all(cfg: dict, raw_dir: str) -> dict:
    ok, failed = [], []
    for snap in cfg["snapshots"]:
        for filename in FILES:
            url = f"{BASE_URL}/{cfg['data_root']}/{snap}/data/{filename}"
            dest = Path(raw_dir) / cfg["city"] / snap / filename      # khớp qa.py: raw/<city>/<mốc>/
            
            if fetch(url, dest):
                ok.append(str(dest))
            else:
                failed.append(str(dest))
                
    return {"ok": ok, "failed": failed}

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--config", required=True)
    p.add_argument("--raw-dir", default="data/raw")
    args = p.parse_args()

    cfg = load_config(args.config)
    res = download_all(cfg, args.raw_dir)
    
    print(f"\nXong: {len(res['ok'])} OK, {len(res['failed'])} lỗi")
    # Trả về mã lỗi 1 nếu có file tải thất bại (để CI/CD hoặc shell script biết)
    raise SystemExit(1 if res["failed"] else 0)
