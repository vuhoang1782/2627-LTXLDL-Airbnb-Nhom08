"""Liệt kê cột của listings / calendar / reviews và % NaN của từng cột ở 4 mốc.

Đầu ra: reports/common_columns_nan.csv
  file | cot | <mốc 1> | <mốc 2> | <mốc 3> | <mốc 4>
Ô rỗng = cột không có ở mốc đó. Mặc định chỉ tính trên các listing được phân công
cho nhóm (cùng cách lọc với bản cũ); thêm --all-rows để tính trên toàn bộ tệp.
"""
import argparse
from pathlib import Path

import pandas as pd
import yaml

OUT_NAME = "common_columns_nan_test.csv"
FILES = {                      # tên tệp (.csv.gz) -> cột ID dùng để lọc theo listing
    "listings": "id",
    "calendar": "listing_id",
    "reviews": "listing_id",
}


def load_ids(path, ma):
    """Lấy listing_id của nhóm `ma` từ PClistings.csv (đọc dạng chuỗi để không mất chữ số)."""
    df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    s = df.loc[df["Mã dữ liệu"].str.strip() == ma, "listing_id"].dropna().str.strip()
    if s.empty:
        raise ValueError(f"Không có listing nào cho '{ma}' trong {path}")
    return set(s.astype("int64"))


def nan_percent(path, id_col, ids, chunksize=200_000):
    """% NaN của mọi cột trong tệp .csv.gz. ids=None: tính trên tất cả các dòng."""
    n, nan = 0, None
    for chunk in pd.read_csv(path, chunksize=chunksize):   # pandas tự giải nén .gz
        if ids is not None:
            chunk = chunk[chunk[id_col].isin(ids)]
        n += len(chunk)
        s = chunk.isna().sum()
        nan = s if nan is None else nan.add(s, fill_value=0)
    return (nan / n * 100).round(1)


def run(cfg_path, all_rows=False):
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    snaps = [str(s) for s in cfg["snapshots"]]
    chk = cfg["check"]
    ids = None if all_rows else load_ids(chk["listing_file"], chk["ma_du_lieu"])
    raw = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]

    rows = {}                                   # (file, cột) -> {mốc: % NaN}
    for snap in snaps:
        for name, id_col in FILES.items():
            print(f"{snap}  {name} ...", flush=True)
            pct = nan_percent(raw / snap / f"{name}.csv.gz", id_col, ids)
            for col, v in pct.items():
                rows.setdefault((name, col), {})[snap] = v

    out = pd.DataFrame([{"file": f, "cot": c, **vals} for (f, c), vals in rows.items()],
                       columns=["file", "cot"] + snaps)
    out = out.sort_values("file", key=lambda c: c.map(list(FILES).index), kind="stable")  # gom theo tệp
    out_dir = Path(cfg.get("reports_dir", "reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_dir / OUT_NAME, index=False)
    print(f"Đã ghi {out_dir / OUT_NAME}: {len(out)} dòng")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--all-rows", action="store_true", help="tính trên toàn bộ tệp, không lọc theo listing của nhóm")
    args = ap.parse_args()
    run(args.config, args.all_rows)
