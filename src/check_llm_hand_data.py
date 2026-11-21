"""Lọc dữ liệu thô theo ID được phân công và ghi ra data/interim/<city>/<mốc>/.

Đầu vào : data/raw/<city>/<mốc>/{listings,calendar,reviews}.csv.gz   (do download.py tải)
          check.listing_file, check.review_file trong yaml             (file phân công của cả lớp)
Đầu ra  : data/interim/<city>/<mốc>/{listings,calendar,reviews}.csv.gz  (chỉ phần dữ liệu của nhóm)
          reports/subset_manifest.csv                                   (mỗi (mốc, bảng) một dòng)

Quy tắc lọc:
  - listings, calendar : lọc theo listing_id (1.000 ID được phân công)
  - reviews            : lọc theo review_id, tức cột `id` của reviews (5.000 ID được phân công)

Cách chạy (đứng ở THƯ MỤC GỐC của repo):
    python src/subset.py --config config/newyork.yaml
"""
from __future__ import annotations

# ── KHỐI 0: IMPORT VÀ HẰNG SỐ ──────────────────────────────────────────────
import argparse                  # đọc tham số dòng lệnh --config
import logging                   # in log INFO / WARNING / ERROR
import sys                       # sys.exit(...) trả mã thoát cho hệ điều hành
from pathlib import Path         # xử lý đường dẫn gọn, không phụ thuộc hệ điều hành

import pandas as pd              # đọc, lọc, ghi CSV
import yaml                      # đọc newyork.yaml (tên cài đặt là PyYAML, tên import là yaml)

# Bộ ghi log tên "subset". Dòng này chỉ TẠO logger; cách in ra được cấu hình ở khối 4.
log = logging.getLogger("subset")

# Số dòng mỗi mảnh khi đọc file lớn (calendar, reviews). Dấu _ chỉ để dễ đọc, Python bỏ qua nó.
CHUNK = 1_000_000


# ── KHỐI 1: ĐỌC FILE PHÂN CÔNG ─────────────────────────────────────────────
def load_assignment(cfg: dict) -> tuple[dict[int, str], set[int], set[int], set[int]]:
    """Trả về 4 thứ lấy từ file phân công của cả lớp:
         1. dict  listing_id -> analysis_area (vùng A01-A08)
         2. set   review_id của nhóm (5.000)
         3. set   review_id thuộc mẫu LLM (1.000)
         4. set   review_id thuộc nhãn tay (100, là tập con của mẫu LLM)
    """
    chk = cfg["check"]               # khối `check` trong yaml
    ma = chk["ma_du_lieu"]           # mã nhóm, vd DSE2049-C04-G08-new-york-city

    # dtype=str: đọc mọi cột dạng chuỗi. ID Airbnb dài tới 19 chữ số, để pandas tự đoán kiểu
    # có thể bị đọc thành số thực và làm tròn mất chữ số cuối. Đọc chuỗi trước, ép int64 sau.
    # encoding="utf-8-sig": đọc được cả file có BOM (ký tự đánh dấu Excel hay thêm vào đầu file).
    L = pd.read_csv(chk["listing_file"], dtype=str, encoding="utf-8-sig")
    # Chỉ giữ dòng của đúng nhóm mình. Cần thiết vì có tới 3 nhóm cùng làm New York.
    L = L[L["Mã dữ liệu"].str.strip() == ma]
    R = pd.read_csv(chk["review_file"], dtype=str, encoding="utf-8-sig")
    R = R[R["Mã dữ liệu"].str.strip() == ma]
    # Gõ sai mã trong yaml thì dừng ngay với thông báo rõ, không để chạy tiếp với dữ liệu rỗng.
    if L.empty or R.empty:
        raise ValueError(f"Không có dòng nào cho mã '{ma}' trong file phân công")

    # Ghép hai cột thành từng cặp rồi đổi thành dict, vd {1234567: "A03", ...}.
    # Dict này dùng ở khối 2 để gắn vùng cho từng listing bằng .map(area).
    area = dict(zip(L["listing_id"].str.strip().astype("int64"), L["analysis_area"].str.strip()))

    # Ép int64 vì cột id / listing_id trong file Airbnb thô là SỐ. Nếu giữ chuỗi thì isin so "123"
    # với 123 sẽ không bao giờ khớp -> 0 dòng mà KHÔNG có thông báo lỗi nào.
    rid = R["review_id"].str.strip().astype("int64")
    # Ô có 'x' là được chọn, ô trống là không. Mặt nạ True/False chọn ra các review_id tương ứng
    # (chạy đúng vì rid được tạo từ chính R nên hai bên cùng chỉ mục).
    llm = set(rid[R["Mẫu LLM"].notna() & (R["Mẫu LLM"].str.strip() != "")])
    hand = set(rid[R["Nhãn tay"].notna() & (R["Nhãn tay"].str.strip() != "")])
    return area, set(rid), llm, hand


# ── KHỐI 2: LỌC TỪNG BẢNG ──────────────────────────────────────────────────
def filter_listings(path: Path, area: dict[int, str]) -> pd.DataFrame:
    """Lọc bảng nhỏ (listings chỉ vài chục MB) bằng cách đọc cả file một lần."""
    # pandas tự nhận file .gz qua đuôi. low_memory=False: đọc cả cột rồi mới đoán kiểu,
    # tránh DtypeWarning vì listings có ~90 cột, nhiều cột lẫn kiểu.
    df = pd.read_csv(path, low_memory=False)
    # isin(dict) duyệt qua các KHÓA của dict, tức 1.000 listing_id. .copy() tạo bản độc lập
    # để dòng gán cột bên dưới không gây SettingWithCopyWarning.
    sub = df[df["id"].isin(area)].copy()
    # Tra dict để gắn vùng A01-A08. Các cột gốc được giữ NGUYÊN vì QA và KPI sau cần nhiều cột.
    sub["analysis_area"] = sub["id"].map(area)
    return sub


def filter_chunked(path: Path, col: str, keep: set[int]) -> pd.DataFrame:
    """Lọc bảng lớn: giữ dòng có cột `col` thuộc `keep`. Dùng chung cho calendar (col=listing_id)
    và reviews (col=id)."""
    # chunksize làm read_csv trả về bộ lặp nhả ra từng DataFrame CHUNK dòng. Mỗi mảnh được lọc ngay
    # rồi bỏ đi, nên bộ nhớ chỉ giữ một mảnh và phần đã lọc (nhỏ) -> không bao giờ tràn RAM.
    parts = [c[c[col].isin(keep)] for c in pd.read_csv(path, chunksize=CHUNK)]
    # ignore_index=True: đánh số lại chỉ mục từ 0. pd.concat([]) báo lỗi với danh sách rỗng nên có nhánh else.
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

def filter_chunked_comment(path: Path, col: str, keep: set[int]) -> pd.DataFrame:
    """Lọc bảng lớn: giữ dòng có cột `col` thuộc `keep`. Dùng chung cho calendar (col=listing_id)
    và reviews (col=id)."""
    # chunksize làm read_csv trả về bộ lặp nhả ra từng DataFrame CHUNK dòng. Mỗi mảnh được lọc ngay
    # rồi bỏ đi, nên bộ nhớ chỉ giữ một mảnh và phần đã lọc (nhỏ) -> không bao giờ tràn RAM.
    parts = [c[c[col].isin(keep) & c[col].notna() & (c[col] != "")] for c in pd.read_csv(path, chunksize=CHUNK)]
    # ignore_index=True: đánh số lại chỉ mục từ 0. pd.concat([]) báo lỗi với danh sách rỗng nên có nhánh else.
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

def write_gz(df: pd.DataFrame, dest: Path) -> None:
    """Ghi file nén an toàn: ghi vào .part rồi mới đổi tên, giống download.py,
    để sự có mặt của dest luôn nghĩa là "đã ghi xong"."""
    dest.parent.mkdir(parents=True, exist_ok=True)           # tạo thư mục data/interim/<city>/<mốc>/
    tmp = dest.with_name(dest.name + ".part")
    # Tên file tạm kết thúc bằng .part nên pandas KHÔNG tự suy ra kiểu nén từ đuôi,
    # phải khai báo compression="gzip" rõ ràng, nếu không sẽ có file .csv.gz là CSV chưa nén.
    df.to_csv(tmp, index=False, compression="gzip")          # index=False: bỏ cột số thứ tự
    tmp.replace(dest)


# ── KHỐI 3: ĐIỀU PHỐI ──────────────────────────────────────────────────────
def run(cfg_path: str) -> int:
    """Ráp các hàm lại. Trả về MÃ THOÁT (0 = ổn, 1 = có bảng lỗi), không trả dữ liệu.
    Vòng lặp: mốc x bảng -> lọc -> gắn cờ (reviews) -> ghi file -> ghi một dòng manifest.
    Một bảng lỗi chỉ ghi 'failed' rồi làm tiếp, không làm dừng cả chương trình."""
    with open(cfg_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    snaps = [str(s) for s in cfg["snapshots"]]     # ép mốc về chuỗi vì YAML tự đổi 2025-09-01 thành kiểu ngày

    # Đọc file phân công MỘT LẦN trước vòng lặp: 1.000 listing và 5.000 review giống nhau ở cả 4 mốc.
    area, rid, llm, hand = load_assignment(cfg)

    # raw_dir / interim_dir lấy từ yaml; nếu yaml không có thì dùng giá trị mặc định.
    raw_root = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]
    out_root = Path(cfg.get("interim_dir", "data/interim")) / cfg["city"]
    manifest = []                                  # mỗi (mốc, bảng) thêm một dòng

    for snap in snaps:
        raw_dir = raw_root / snap
        out_dir = out_root / snap
        # Mỗi bảng: (file nguồn, file đích). Thứ tự listings -> calendar -> reviews là có chủ đích:
        # số dòng calendar kỳ vọng phụ thuộc số listing tìm được ở cùng mốc.
        tables = {
            "listings": (raw_dir / "listings.csv.gz", out_dir / "listings_filtered.csv.gz"),
            "calendar": (raw_dir / "calendar.csv.gz", out_dir / "calendar_filtered.csv.gz"),
            "reviews": (raw_dir / "reviews.csv.gz", out_dir / "reviews_filtered.csv.gz"),
        }
        n_listings = None                          # số listing thực sự tìm được ở mốc này

        for table, (source, dest) in tables.items():
            # Dòng ghi nhận, khai báo đủ trường để dòng nào cũng đủ cột.
            row = {"snapshot": snap, "table": table, "source": str(source), "path": str(dest),
                   "status": "", "rows": 0, "expected": None, "availible_llm_id": 0, "availible_handlabel_id": 0,"message": ""}
            try:
                if table == "listings":
                    sub = filter_listings(source, area)
                    n_listings = len(sub)
                    row["expected"] = len(area)                    # 1.000 listing
                elif table == "calendar":
                    sub = filter_chunked(source, "listing_id", set(area))   # set(area) = tập 1.000 khóa
                    # 365 ngày mỗi listing THỰC CÓ ở mốc này (mốc thiếu 9 listing -> 991 x 365, không phải 365.000)
                    row["expected"] = n_listings * 365 if n_listings is not None else None
                else:
                    # Reviews lọc theo review_id (cột `id`), KHÔNG lọc theo listing_id:
                    # lọc theo listing_id sẽ lấy mọi review của listing (hàng chục nghìn) thay vì đúng 5.000.
                    sub = filter_chunked_comment(source, "id", rid)
                    row["expected"] = len(rid)                     # 5.000 review
                    if not sub.empty:
                        # Gắn cờ thay vì tách file: các bước sau chỉ cần sub[sub.is_llm] / sub[sub.is_hand].
                        review_ids = pd.to_numeric(sub["id"], errors="coerce").astype("Int64")
                        sub["is_llm"] = review_ids.isin(llm)
                        sub["is_hand"] = review_ids.isin(hand)
                        row["availible_llm_id"] = (review_ids.isin(llm)).sum()
                        row["availible_handlabel_id"] = review_ids.isin(hand).sum()

                write_gz(sub, dest)
                row["status"] = "ok"
                row["rows"] = len(sub)
                # Lệch số chỉ CẢNH BÁO, không tính là lỗi: một listing có thể bị gỡ khỏi Airbnb ở mốc đó.
                # Cảnh báo cũng bắt được lỗi im lặng nguy hiểm nhất: lọc ra 0 dòng do lệch kiểu ID.
                if row["expected"] is not None and len(sub) != row["expected"]:
                    log.warning("%s/%s lệch số: %d dòng (kỳ vọng %d)", snap, table, len(sub), row["expected"])
            except Exception as e:                 # file thiếu / hỏng: ghi lại rồi làm tiếp bảng sau
                row["status"] = "failed"
                row["message"] = str(e)
                log.error("%s/%s: %s", snap, table, e)
            manifest.append(row)                   # nằm NGOÀI try, trong vòng lặp bảng: bảng nào cũng để lại một dòng

    reports_dir = Path(cfg.get("reports_dir", "reports"))
    reports_dir.mkdir(parents=True, exist_ok=True)
    out = reports_dir / "subset_manifest.csv"
    pd.DataFrame(manifest).to_csv(out, index=False)    # file này bị ghi đè mỗi lần chạy

    failed = [row for row in manifest if row["status"] == "failed"]
    log.info("Xong: %d bảng, %d lỗi. Manifest: %s", len(manifest), len(failed), out)
    # Danh sách rỗng là "sai" nên trả 0 nếu không lỗi, 1 nếu có lỗi (quy ước shell: 0 = thành công).
    return 1 if failed else 0


# ── KHỐI 4: ĐIỂM VÀO ───────────────────────────────────────────────────────
# __name__ bằng "__main__" khi chạy trực tiếp, và bằng "subset" khi bị import từ nơi khác
# (vd run_all.py), nhờ vậy import không vô tình kích hoạt việc lọc.
if __name__ == "__main__":
    # Cấu hình cách in log: từ mức INFO trở lên, mỗi dòng gồm "MỨC nội dung".
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)         # bắt buộc: đường dẫn file yaml
    sys.exit(run(ap.parse_args().config))              # run() trả 0 hoặc 1, sys.exit đưa ra làm mã thoát