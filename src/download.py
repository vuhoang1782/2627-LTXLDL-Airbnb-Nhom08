"""Bước 1: tải 4 mốc x 3 tệp từ Inside Airbnb (data/raw) rồi lọc theo ID của nhóm (data/interim).

Chạy riêng:  python -m src.download --config configs/new_york_city.yaml [--snapshot YYYY-MM-DD] [--download-only | --filter-only]
Ra:  data/raw/<mốc>/<bảng>.csv.gz  và  data/interim/<mốc>/<bảng>_filtered.csv.gz
     (chữ gốc nguyên văn, ID dạng chuỗi, giữ nguyên cột của tệp nguồn; reviews thêm 3 cột: assigned_listing_id, mau_llm, nhan_tay)
Tệp phân công (config: assignments) là CSV: listing_ids cần cột listing_id (hoặc id); review_ids cần cột review_id,
nên có thêm listing_id, «Mẫu LLM», «Nhãn tay» (ô có chữ x = thuộc mẫu). Nếu tệp là của cả lớp (có cột «Lớp», «Nhóm»)
thì quy trình chỉ giữ dòng của nhóm khai trong config (group).
Không có mục assignments trong config (vd. thành phố khác) thì lấy mẫu ngẫu nhiên cố định theo seed.
"""
import argparse
import gzip
import shutil
import sys
import time
import urllib.error
import urllib.request

import pandas as pd

from src.utils import TABLES, ensure_dir, folder, get_logger, load_config

log = get_logger("download")
TIMEOUT, RETRIES, BACKOFF = 60, 3, 2.0
CAL_COLS = ["listing_id", "date", "available", "minimum_nights", "maximum_nights"]


# ---------------------------------------------------------------- bước 1: tải
def is_valid(path):
    """Tệp tồn tại, không rỗng và gzip đọc hết được."""
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with gzip.open(path, "rb") as f:
            while f.read(1 << 20):
                pass
        return True
    except (OSError, EOFError):
        return False


def download(url, dest):
    """Trả về None nếu tải được, ngược lại trả về chuỗi lỗi."""
    ensure_dir(dest.parent)
    part, err = dest.with_suffix(dest.suffix + ".part"), None
    for attempt in range(RETRIES):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(part, "wb") as f:
                expected = r.headers.get("Content-Length")
                shutil.copyfileobj(r, f)
                f.flush()
                if expected is not None and f.tell() != int(expected):
                    raise OSError(f"tải thiếu: {f.tell()}/{expected} byte")
            part.replace(dest)
            return None
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if 400 <= e.code < 500 and e.code != 429:     # lỗi phía yêu cầu: thử lại vô ích
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            err = f"Network/IO error: {e}"
        finally:
            part.unlink(missing_ok=True)
        if attempt < RETRIES - 1:
            time.sleep(BACKOFF * 2 ** attempt)
    return err


def fetch(url, dest):
    if is_valid(dest):
        log.info("[skip] %s", dest)
        return True
    err = download(url, dest) or (None if is_valid(dest) else "gzip hỏng")
    if err:
        dest.unlink(missing_ok=True)
        log.error("[fail] %s -> %s", url, err)
        return False
    log.info("[ok]   %s", dest)
    return True


def download_all(cfg, snaps):
    base = cfg.get("base_url", "https://data.insideairbnb.com").rstrip("/")
    ok = [fetch(f"{base}/{cfg['data_root'].strip('/')}/{s}/data/{t}.csv.gz", folder(cfg, "raw", s) / f"{t}.csv.gz")
          for s in snaps for t in TABLES]
    return all(ok)


# ---------------------------------------------------------------- bước 2: lọc theo tệp phân công
def filter_table(path, key, keep, usecols=None, chunksize=500_000):
    """Đọc theo khối, mọi cột là chuỗi nguyên văn, giữ dòng có key thuộc keep."""
    chunks = pd.read_csv(path, dtype=str, keep_default_na=False, chunksize=chunksize, usecols=usecols)
    return pd.concat([c[c[key].isin(keep)] for c in chunks], ignore_index=True)


def read_assignments(cfg):
    """Trả về (tập listing_id, bảng review: review_id, assigned_listing_id, mau_llm, nhan_tay)."""
    a = cfg.get("assignments")
    if not a:
        return sample_assignments(cfg)
    load = lambda k: pd.read_csv(cfg["_dir"] / a[k], dtype=str, keep_default_na=False, encoding="utf-8-sig") \
        .rename(columns=str.strip).apply(lambda s: s.str.strip())
    lst, rev = load("listing_ids"), load("review_ids")
    g = cfg.get("group")
    if g and "Lớp" in lst and "Lớp" in rev:                          # tệp của cả lớp: chỉ giữ dòng của nhóm
        mine = lambda d: d[(d["Lớp"] == g["class"]) & (d["Nhóm"] == str(g["number"]))]
        lst, rev = mine(lst), mine(rev)
    if "listing_id" not in lst and "id" in lst:                      # chấp nhận tên cột 'id'
        lst = lst.rename(columns={"id": "listing_id"})
    for df, col, name in ((lst, "listing_id", "listing_ids"), (rev, "review_id", "review_ids")):
        if col not in df or df[col].eq("").any() or df[col].duplicated().any():
            sys.exit(f"{a[name]}: thiếu cột '{col}', có ô rỗng hoặc ID trùng")
    llm_col, hand_col = a.get("llm_flag_column", "Mẫu LLM"), a.get("hand_flag_column", "Nhãn tay")
    if llm_col not in rev or hand_col not in rev:
        log.warning("review_ids thiếu cột '%s' hoặc '%s' -> không có manifest mẫu LLM, QA09 sẽ chặn KPI 6/7", llm_col, hand_col)
    flag = lambda c: rev[c].str.lower().eq("x") if c in rev else pd.Series(False, index=rev.index)
    manifest = pd.DataFrame({"review_id": rev["review_id"], "assigned_listing_id": rev["listing_id"] if "listing_id" in rev else "",
                             "mau_llm": flag(llm_col), "nhan_tay": flag(hand_col)})
    return set(lst["listing_id"]), manifest


def sample_assignments(cfg):
    """Không có tệp phân công: lấy mẫu cố định theo seed để quy trình vẫn chạy được."""
    seed, size, llm = cfg.get("seed", 42), cfg.get("fallback_sample", {}), cfg["llm"]
    log.warning("Config không có 'assignments' -> lấy mẫu ngẫu nhiên (seed=%s)", seed)
    first, last = cfg["snapshots"][0], cfg["snapshots"][cfg["kpi"]["llm_snapshot_index"]]
    ids = pd.read_csv(folder(cfg, "raw", first) / "listings.csv.gz", dtype=str, keep_default_na=False, usecols=["id"])["id"].drop_duplicates()
    lids = set(ids.sample(min(len(ids), size.get("listings", 1000)), random_state=seed))
    rev = filter_table(folder(cfg, "raw", last) / "reviews.csv.gz", "listing_id", lids, ["listing_id", "id"]).drop_duplicates("id")
    rev = rev.sample(min(len(rev), size.get("reviews", 5000)), random_state=seed).reset_index(drop=True)
    manifest = pd.DataFrame({"review_id": rev["id"], "assigned_listing_id": rev["listing_id"],
                             "mau_llm": rev.index < llm["sample_size"], "nhan_tay": rev.index < llm["hand_label_size"]})
    return lids, manifest


def run_filter(cfg, snaps):
    lids, manifest = read_assignments(cfg)
    rids, info = set(manifest["review_id"]), manifest.set_index("review_id")
    cal, problems = set(cfg.get("calendar_columns", CAL_COLS)), []
    for snap in snaps:
        raw, out = folder(cfg, "raw", snap), ensure_dir(folder(cfg, "interim", snap))
        if not all((raw / f"{t}.csv.gz").exists() for t in TABLES):
            problems.append(f"{snap}: chưa có đủ tệp raw")
            continue
        data = {"listings": filter_table(raw / "listings.csv.gz", "id", lids),
                "calendar": filter_table(raw / "calendar.csv.gz", "listing_id", lids, lambda c: c in cal),   # cột thiếu thì bỏ qua (QA01 báo)
                "reviews": filter_table(raw / "reviews.csv.gz", "id", rids)}
        for col in ("assigned_listing_id", "mau_llm", "nhan_tay"):
            data["reviews"][col] = data["reviews"]["id"].map(info[col])
        for t, df in data.items():
            df.to_csv(out / f"{t}_filtered.csv.gz", index=False, compression="gzip")
        L, C, R = data["listings"], data["calendar"], data["reviews"]
        log.info("[filter] %s: listings %d/%d, calendar %s, reviews %d/%d", snap, len(L), len(lids), f"{len(C):,}", len(R), len(rids))
        if L["id"].duplicated().any() or R["id"].duplicated().any():
            log.warning("%s: có id trùng trong listings hoặc reviews (QA02 sẽ xử lý, không dừng)", snap)
        if len(L) < len(lids) or len(R) < len(rids):
            log.warning("thiếu %d listing, %d review ở %s", len(lids) - len(L), len(rids) - len(R), snap)
    return problems


def run(cfg, snapshot=None, download_only=False, filter_only=False):
    snaps = [snapshot] if snapshot else cfg["snapshots"]
    ok = True if filter_only else download_all(cfg, snaps)
    problems = [] if download_only else run_filter(cfg, snaps)
    for msg in problems:
        log.error("[lỗi] %s", msg)
    if not ok or problems:
        raise SystemExit("Tải/lọc dữ liệu chưa hoàn chỉnh, xem thông báo ở trên")


def main():
    p = argparse.ArgumentParser(description="Tải dữ liệu Inside Airbnb và lọc theo ID của nhóm.")
    p.add_argument("--config", required=True)
    p.add_argument("--snapshot", help="chỉ một mốc YYYY-MM-DD")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true")
    mode.add_argument("--filter-only", action="store_true")
    a = p.parse_args()
    cfg = load_config(a.config)
    if a.snapshot and a.snapshot not in cfg["snapshots"]:
        p.error(f"{a.snapshot} không có trong {a.config}")
    run(cfg, a.snapshot, a.download_only, a.filter_only)


if __name__ == "__main__":
    main()
