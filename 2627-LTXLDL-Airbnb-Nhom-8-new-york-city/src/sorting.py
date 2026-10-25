"""Lọc dữ liệu theo ID được phân công và xuất check_<ma_du_lieu>.csv."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import yaml

TABLES = ["listings", "calendar", "reviews"]
OUT_COLS = ["ma_du_lieu", "moc", "ngay", "tai_ve_ok",
            "listings_bytes", "calendar_bytes", "reviews_bytes",
            "listings_dong", "calendar_dong", "reviews_dong",
            "entire_home", "private_room", "khong_co_review", "thieu_price",
            "so_cot_listings", "so_cot_nan_90"]


def load_ids(path: str, ma: str, id_col: str, flag_col: str | None = None) -> set[int]:
    """Lấy ID của nhóm `ma` từ tệp phân công dùng chung của cả lớp.

    flag_col: nếu có, chỉ giữ dòng mà cột này không rỗng (vd. 'Mẫu LLM', 'Nhãn tay').
    Đọc dạng chuỗi rồi mới ép int64 để ID 19 chữ số không bị làm tròn.
    """
    p = Path(path)
    df = (pd.read_excel(p, dtype=str) if p.suffix in (".xlsx", ".xls")
          else pd.read_csv(p, dtype=str, encoding="utf-8-sig"))
    df = df[df["Mã dữ liệu"].str.strip() == ma]
    if flag_col:
        f = df[flag_col].fillna("").astype(str).str.strip().str.lower()
        df = df[~f.isin(["", "0", "false", "no", "nan"])]
    s = df[id_col].dropna().str.strip()
    if s.empty:
        raise ValueError(f"Không có dòng nào cho '{ma}' (cột {flag_col or id_col}) trong {p}")
    return set(s.astype("int64"))        # sai định dạng -> báo lỗi to, không im lặng


def scan(path: Path, ids: set[int], id_col: str, keep_col: str | None = None,
         chunksize: int = 1_000_000) -> tuple[int, set]:
    """Đếm số dòng có id_col thuộc ids, đọc theo chunk để không tràn RAM."""
    usecols = [id_col] + ([keep_col] if keep_col else [])
    n, kept = 0, set()
    for chunk in pd.read_csv(path, usecols=usecols, chunksize=chunksize):
        m = chunk[id_col].isin(ids)
        n += int(m.sum())
        if keep_col:
            kept.update(chunk.loc[m, keep_col].tolist())
    return n, kept


def check_listings(path: Path, ids: set[int]) -> tuple[dict, list[tuple[str, float]]]:
    df = pd.read_csv(path, low_memory=False)
    sub = df[df["id"].isin(ids)]
    nan_pct = sub.isna().mean() if len(sub) else pd.Series(dtype=float)
    cols90 = [(c, round(float(v) * 100, 2)) for c, v in nan_pct.items() if v >= 0.9]
    return {
        "listings_dong": len(sub),
        "entire_home": int((sub["room_type"] == "Entire home/apt").sum()),
        "private_room": int((sub["room_type"] == "Private room").sum()),
        "khong_co_review": int((sub["number_of_reviews"] == 0).sum()),
        "thieu_price": int(sub["price"].isna().sum()),
        "so_cot_listings": df.shape[1],            # số cột của cả tệp
        "so_cot_nan_90": len(cols90),
    }, cols90


def tai_ve_ok(man: pd.DataFrame, snap: str, raw_dir: Path) -> str:
    m = man[(man["snapshot"] == snap) & (man["table"].isin(TABLES))]
    codes = m["http_status"].dropna().astype(str)
    codes = codes[codes != ""]
    if len(codes):                       # có mã lỗi HTTP -> ghi mã đó
        return codes.iloc[0]
    if all((raw_dir / snap / f"{t}.csv.gz").exists() for t in TABLES):
        return "co"                      # đủ 3 tệp trên đĩa
    return "loi"


def run(cfg_path: str) -> int:
    cfg = yaml.safe_load(open(cfg_path, encoding="utf-8"))
    snaps = [str(s) for s in cfg["snapshots"]]
    chk = cfg["check"]
    ma = chk["ma_du_lieu"]
    ids = load_ids(chk["listing_file"], ma, "listing_id")
    llm_ids = load_ids(chk["review_file"], ma, "review_id", "Mẫu LLM")
    hand_ids = load_ids(chk["review_file"], ma, "review_id", "Nhãn tay")
    print(f"{len(ids)} listing, {len(llm_ids)} review LLM, {len(hand_ids)} nhãn tay được phân công")

    raw = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]
    out_dir = Path(cfg.get("reports_dir", "reports"))
    out_dir.mkdir(parents=True, exist_ok=True)
    man = pd.read_csv(out_dir / "download_manifest.csv", dtype=str)

    rows, cols90_all, errors = [], [], []
    found_llm, found_hand = set(), set()
    for i, snap in enumerate(snaps, 1):
        row = dict.fromkeys(OUT_COLS)             # NaN mặc định = ô rỗng
        row.update(ma_du_lieu=ma, moc=i, ngay=snap, tai_ve_ok=tai_ve_ok(man, snap, raw))
        for t in TABLES:
            p = raw / snap / f"{t}.csv.gz"
            if p.exists():
                row[f"{t}_bytes"] = p.stat().st_size
        try:
            stats, cols90 = check_listings(raw / snap / "listings.csv.gz", ids)
            row.update(stats)
            cols90_all += [(snap, c, v) for c, v in cols90]
            row["calendar_dong"], _ = scan(raw / snap / "calendar.csv.gz", ids, "listing_id")
            row["reviews_dong"], rv = scan(raw / snap / "reviews.csv.gz", ids, "listing_id", keep_col="id")
            found_llm |= rv & llm_ids
            found_hand |= rv & hand_ids
        except Exception as e:                    # file thiếu / hỏng -> ghi cho câu 1
            errors.append((snap, type(e).__name__, str(e)))
        rows.append(row)

    out = out_dir / f"check_{ma}.csv"
    num = OUT_COLS[4:]
    df_out = pd.DataFrame(rows, columns=OUT_COLS)
    df_out[num] = df_out[num].astype("Int64")     # số nguyên, NaN -> ô rỗng
    df_out.to_csv(out, index=False)
    pd.DataFrame(cols90_all, columns=["moc", "cot", "nan_pct"]).to_csv(
        out_dir / f"check_{ma}_cols90.csv", index=False)

    print(f"Đã ghi {out}")
    print(f"[Câu 1] lỗi: {errors or 'không có'}")
    print(f"[Câu 2] LLM: {len(found_llm)}/{len(llm_ids)}  nhãn tay: {len(found_hand)}/{len(hand_ids)}")
    print(f"[Câu 3] xem {out_dir / f'check_{ma}_cols90.csv'}")
    return 1 if errors else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    sys.exit(run(ap.parse_args().config))
