import shutil
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml

BASE_URL = "https://data.insideairbnb.com"
FILES = ["data/listings.csv.gz", "data/calendar.csv.gz", "data/reviews.csv.gz"]
TIMEOUT, MAX_RETRIES, BACKOFF = 30, 3, 2.0


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["snapshots"] = [str(s) for s in cfg["snapshots"]]
    return cfg


def _download_one(url: str, dest: Path) -> str | None:
    """Trả về None nếu OK, ngược lại trả về thông báo lỗi."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    err = None

    for attempt in range(MAX_RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
            part.replace(dest)
            return None
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if 400 <= e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = f"Network error: {e}"
        finally:
            part.unlink(missing_ok=True)
        time.sleep(BACKOFF * 2**attempt)
    return err


def download_all(cfg: dict, raw_dir: str) -> dict:
    ok, failed = [], []
    for snap in cfg["snapshots"]:
        for rel in FILES:
            url = f"{BASE_URL}/{cfg['data_root']}/{snap}/{rel}"
            dest = Path(raw_dir) / cfg["city"] / snap / Path(rel).name
            err = _download_one(url, dest)
            (failed if err else ok).append({"path": str(dest), "error": err})
            print(f"{'FAIL: ' + err if err else 'OK'} {dest}")
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
    raise SystemExit(1 if res["failed"] else 0)
