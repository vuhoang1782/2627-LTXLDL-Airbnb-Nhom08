"""Tải dữ liệu Inside Airbnb theo file cấu hình (yaml) và kiểm tra tính toàn vẹn.
 
Luồng tổng quát của chương trình:
    đọc yaml -> với mỗi (mốc snapshot x loại file):
        bỏ qua nếu file cũ còn tốt -> ngược lại thì tải -> kiểm tra -> tính SHA-256
    -> ghi bảng tổng kết (manifest) ra CSV -> trả mã thoát 0 (ổn) hoặc 1 (có lỗi).
 
Cách chạy (đứng ở THƯ MỤC GỐC của repo, vì các đường dẫn bên dưới là đường dẫn tương đối):
    python src/download.py --config config/newyork.yaml
    python src/download.py --config config/newyork.yaml --force   # ép tải lại tất cả
"""
# Bản cũ viết lặp lại dòng này giữa file nên Python báo SyntaxError.
# Tác dụng: cho phép viết kiểu gợi ý như `str | None` mà không lỗi trên Python cũ.
from __future__ import annotations
 
# ── KHỐI 1: IMPORT ─────────────────────────────────────────────────────────
# Thư viện chuẩn của Python (có sẵn, không cần pip install)
import argparse                              # đọc tham số dòng lệnh: --config, --force
import gzip                                  # mở và giải nén thử file .gz để phát hiện file cụt
import hashlib                               # tính SHA-256 (dấu vân tay của file)
import json                                  # đọc file GeoJSON
import logging                               # in log có mức độ INFO / WARNING / ERROR
import sys                                   # sys.exit(...) để trả mã thoát cho hệ điều hành
import time                                  # time.sleep(...) để chờ giữa các lần thử lại
from datetime import datetime, timezone      # ghi thời điểm tải theo giờ UTC
from pathlib import Path                     # xử lý đường dẫn gọn, không phụ thuộc hệ điều hành
 
# Thư viện ngoài (cần cài: pip install -r requirements.txt)
import pandas as pd                          # đọc dòng tiêu đề CSV; ghi manifest ra CSV
import requests                              # gửi HTTP GET, tải dạng stream
import yaml                                  # đọc newyork.yaml (tên cài đặt là PyYAML, tên import là yaml)
 
# ── KHỐI 2: HẰNG SỐ ────────────────────────────────────────────────────────
# Hằng số = giá trị cố định, đặt một lần ở đầu file, viết HOA. Cần đổi thì chỉ sửa một chỗ.
 
# Phần đầu chung của mọi URL. URL đầy đủ = BASE_URL / data_root / snapshot / rel
# Ví dụ: https://data.insideairbnb.com/united-states/ny/new-york-city/2025-09-01/data/listings.csv.gz
BASE_URL = "https://data.insideairbnb.com"
 
# Tiêu đề HTTP gửi kèm mỗi yêu cầu. User-Agent là dòng "tự giới thiệu".
# Nếu không khai báo, requests tự xưng là "python-requests" và có thể bị chặn (lỗi 403).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
 
# FILES: dict lồng dict, mô tả MỖI LOẠI file cần tải.
#   "rel"      : đường dẫn của file bên trong thư mục snapshot trên máy chủ
#   "required" : các cột BẮT BUỘC phải có; validate_file dùng để phát hiện file sai/thiếu cột
# Muốn tải thêm một loại file thì chỉ cần thêm một mục vào đây, vòng lặp trong run() tự xử lý.
FILES = {
    # listings: cột id là khóa nối bảng; price cho KPI giá; neighbourhood_cleansed là area_col trong yaml;
    # latitude/longitude cho bản đồ và vùng A01-A08; room_type tách cả căn / phòng riêng;
    # last_scraped dùng để khử trùng (dedupe_keys) và đối chiếu mốc.
    "listings": {
        "rel": "data/listings.csv.gz",
        "required": ["id", "price", "neighbourhood_cleansed", "latitude",
                     "longitude", "room_type", "minimum_nights", "last_scraped"],
    },
    # calendar: KHÔNG yêu cầu cột price vì calendar mốc 2026 không có cột này
    # (hoặc có nhưng rỗng 100%). Giá lấy từ listings. Nên ghi quyết định này vào báo cáo QA.
    "calendar": {
        "rel": "data/calendar.csv.gz",
        "required": ["listing_id", "date", "available", "minimum_nights"],
    },
    # reviews: comments là nội dung đưa cho LLM phân loại.
    "reviews": {
        "rel": "data/reviews.csv.gz",
        "required": ["listing_id", "id", "date", "comments"],
    },
    # neighbourhoods: GeoJSON không có "cột" CSV nên required rỗng;
    # nó được kiểm tra riêng (có "features" hay không) trong validate_file.
    "neighbourhoods": {
        "rel": "visualisations/neighbourhoods.geojson",
        "required": [],
    },
}
 
# Tạo bộ ghi log tên "download". Dòng này chỉ TẠO logger;
# cách in ra màn hình được cấu hình bằng logging.basicConfig ở khối 7.
log = logging.getLogger("download")
 
# ── KHỐI 3: LỚP LỖI RIÊNG ──────────────────────────────────────────────────
class DownloadError(Exception):
    """Lỗi khi máy chủ trả mã HTTP >= 400, mang theo mã đó để phân loại.
 
    Vì sao cần: requests KHÔNG tự coi 404 là lỗi (nó vẫn trả về bình thường),
    nên ta tự ném lỗi riêng. Có mã HTTP trong lỗi thì code phía sau mới phân biệt được:
      - 4xx (403, 404): lỗi phía người gửi, thử lại vô ích -> báo ngay
      - 5xx (500, 503): lỗi tạm thời của máy chủ -> đáng thử lại
    Kế thừa từ Exception nên dùng được với raise / except như mọi lỗi khác.
    """
 
    def __init__(self, status, url):
        # status, url là THAM SỐ của hàm này (không phải biến có sẵn trong Exception);
        # chúng nhận giá trị từ nơi gọi: raise DownloadError(404, url)
        # Dòng này giao cho Exception việc lưu chuỗi thông báo, để str(e) trả về "HTTP 404: ...".
        super().__init__(f"HTTP {status}: {url}")
        # Exception chỉ giữ một chuỗi chữ, nên ta tự lưu mã HTTP dạng số
        # để so sánh được (vd e.status < 500).
        self.status = status
 
# ── KHỐI 4: HÀM TẢI ────────────────────────────────────────────────────────
def download_file(url, dest, retries=3, timeout=60) -> None:
    """Tải một URL về đường dẫn dest. Không trả về gì: thành công thì file nằm ở dest,
    thất bại thì ném lỗi lên cho run() xử lý.
 
    Ba kỹ thuật chính:
      1. stream=True : nhận dữ liệu từng mảnh, không nạp cả file (calendar rất lớn) vào RAM
      2. ghi vào file .part rồi mới đổi tên : sự có mặt của dest luôn nghĩa là "đã tải xong"
      3. thử lại với thời gian chờ tăng dần (2, 4, 8 giây) cho lỗi tạm thời
    """
    # Tạo thư mục chứa file đích; parents=True tạo cả thư mục cha còn thiếu,
    # exist_ok=True để không báo lỗi nếu thư mục đã có.
    dest.parent.mkdir(parents=True, exist_ok=True)
 
    # File tạm: listings.csv.gz -> listings.csv.gz.part
    # Phải lấy tên file (dest.name, là chuỗi) rồi mới cộng.
    tmp = dest.with_name(dest.name + ".part")
 
    # attempt chạy 1, 2, ..., retries (bắt đầu từ 1 để 2**attempt cho ra 2, 4, 8 giây
    # và phép so sánh `attempt == retries` đọc tự nhiên). Biến này do vòng for tự tạo.
    for attempt in range(1, retries + 1):
        try:
            # timeout=60: tối đa 60 giây chờ kết nối / chờ dữ liệu kế tiếp (không phải tổng thời gian tải)
            with requests.get(url, stream=True, timeout=timeout, headers=HEADERS) as r:
                # Kiểm tra mã trạng thái: nếu thiếu dòng này, trang lỗi 404 sẽ bị ghi thành file như bình thường
                if r.status_code >= 400:
                    raise DownloadError(r.status_code, url)
                # SỬA: khối ghi file phải THỤT VÀO BÊN TRONG `with requests.get(...)`.
                # Bản cũ để nó ra ngoài, lúc đó kết nối đã đóng nên r.iter_content không đọc được.
                with open(tmp, "wb") as f:                      # "wb" = ghi nhị phân (file .gz không phải văn bản)
                    for chunk in r.iter_content(1 << 20):       # 1 << 20 = 2^20 byte = 1 MiB mỗi mảnh
                        f.write(chunk)
            # Chỉ khi tải TRỌN VẸN mới đổi .part thành tên thật.
            # Nếu mất mạng giữa chừng, dest không bao giờ chứa file cụt.
            tmp.replace(dest)
            return                                              # thành công: thoát hàm, không thử nữa
 
        except DownloadError as e:
            # Xóa file .part dở dang. missing_ok=True: không báo lỗi nếu file chưa được tạo
            # (khi gặp 404, lỗi được ném TRƯỚC dòng open(tmp) nên .part chưa tồn tại).
            tmp.unlink(missing_ok=True)
            # 4xx (403/404) thử lại vô ích; hoặc đã hết lượt -> ném lỗi tiếp lên run().
            # `raise` đứng một mình = ném lại đúng lỗi vừa bắt.
            if e.status < 500 or attempt == retries:
                raise
            time.sleep(2 ** attempt)                            # 5xx còn lượt: chờ 2, 4, ... giây rồi thử lại
 
        except requests.RequestException:
            # Lỗi mạng: timeout, đứt kết nối, lỗi DNS... (RequestException là lớp cha của các lỗi này)
            tmp.unlink(missing_ok=True)
            if attempt == retries:
                raise
            time.sleep(2 ** attempt)
        # Dòng đó chạy sau mỗi lần lỗi (khi .part đã bị xóa) nên gây FileNotFoundError. Đã bỏ.
 
# ── KHỐI 5: HÀM HỖ TRỢ ─────────────────────────────────────────────────────
def load_config(path: str) -> dict:
    """Đọc file yaml thành dict và ép các mốc snapshot về chuỗi."""
    # encoding="utf-8" cần thiết vì yaml có tiếng Việt (aspects: [vị trí, sạch sẽ, ...])
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)        # safe_load không thực thi code lạ nhúng trong yaml
    # YAML tự nhận 2025-09-01 là kiểu ngày (datetime.date), không phải chuỗi.
    # Ép về str một lần ở đây để mọi nơi sau dùng chuỗi.
    # SỬA: bản cũ viết `str[s]` (ngoặc vuông). Gọi hàm phải dùng ngoặc tròn: `str(s)`.
    cfg["snapshots"] = [str(s) for s in cfg["snapshots"]]
    return cfg
 
 
def build_url(data_root: str, snapshot: str, rel: str) -> str:
    """Ghép URL đầy đủ. Chỉ ghép chuỗi, không gọi mạng nên rất dễ tự kiểm thử."""
    return f"{BASE_URL}/{data_root}/{snapshot}/{rel}"
 
 
def validate_file(path: Path, kind: str, snapshot: str) -> None:
    """Kiểm tra file tải về có dùng được không. Không trả về gì:
    file ổn thì chạy xong im lặng, file hỏng thì ném lỗi (run() sẽ bắt và ghi 'failed').
    """
    spec = FILES[kind]                                  # lấy thông số của loại file này từ hằng số FILES
    if path.suffix == ".gz":
        # Lớp 1 (rẻ nhất): mọi file gzip đều bắt đầu bằng 2 byte 1f 8b ("magic bytes").
        # Bắt được trường hợp máy chủ trả trang HTML lỗi nhưng đặt đuôi .gz.
        with open(path, "rb") as f:
            if f.read(2) != b"\x1f\x8b":
                raise ValueError("Không phải file gzip")
        # Lớp 2 (tốn thời gian nhất): giải nén thử toàn bộ, đọc từng mảnh 1 MiB rồi bỏ đi.
        # File bị cụt giữa chừng vẫn có 2 byte đầu đúng, nhưng sẽ lỗi ở chỗ thiếu.
        with gzip.open(path, "rb") as g:
            while g.read(1 << 20):                      # read trả về b"" khi hết file -> vòng while dừng
                pass
        # Lớp 3: kiểm tra cột bắt buộc. nrows=0 chỉ đọc dòng tiêu đề nên rất nhanh.
        cols = set(pd.read_csv(path, nrows=0).columns)
        missing_cols = set(spec["required"]) - cols     # phép trừ tập hợp: cột CẦN mà KHÔNG CÓ
        if missing_cols:
            raise ValueError(f"Thiếu cột khoá: {sorted(missing_cols)}")
        # Lớp 4 (chỉ cho listings): đối chiếu last_scraped với tên mốc, để phát hiện tải nhầm mốc.
        # last_scraped có thể lệch vài ngày so với tên thư mục nên chỉ CẢNH BÁO, không báo lỗi.
        if kind == "listings":
            scraped = set(pd.read_csv(path, usecols=["last_scraped"], nrows=1000)["last_scraped"].astype(str))
            if snapshot not in scraped:
                log.warning("%s: last_scraped %s không chứa mốc %s", path.name, sorted(scraped)[:3], snapshot)
    else:
        # Nhánh GeoJSON. json.load đọc TOÀN BỘ file một lần (không đọc theo mảnh) rồi đổi thành dict/list Python.
        # Chấp nhận được vì file này nhỏ; calendar thì rất lớn nên mới phải đọc theo mảnh ở nhánh .gz.
        with open(path, encoding="utf-8") as f:
            gj = json.load(f)
        # "features" là danh sách các khu phố; mỗi feature có "properties" (tên khu) và "geometry" (đường viền).
        # SỬA: bản cũ viết "feature" (thiếu s) nên luôn báo thiếu. Đúng là "features".
        # .get trả None nếu thiếu khóa; cả None lẫn [] đều là "sai" nên `not` bắt được cả hai.
        if not gj.get("features"):
            raise ValueError("GeoJSON không có features")
 
 
def sha256_of(path) -> str:
    """Tính SHA-256: biến nội dung file thành chuỗi 64 ký tự hex ("dấu vân tay").
    Hai file giống hệt nhau cho cùng kết quả; khác một byte là kết quả khác hẳn.
    Ghi vào manifest để chứng minh dữ liệu không đổi giữa các lần chạy."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # iter(hàm, giá_trị_dừng): gọi f.read(1 MiB) lặp đi lặp lại cho tới khi nó trả về b"" (hết file).
        # Đọc từng mảnh để file lớn không chiếm hết RAM.
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()
 
# ── KHỐI 6: HÀM ĐIỀU PHỐI ──────────────────────────────────────────────────
def run(config_path: str, force: bool = False) -> int:
    """Ráp các hàm lại với nhau. Trả về MÃ THOÁT (0 = ổn, 1 = có file lỗi), không trả dữ liệu.
 
    Vòng lặp: snapshot x loại file -> bỏ qua / tải -> kiểm tra -> ghi hash
    -> bắt lỗi từng file (một file lỗi KHÔNG làm dừng cả chương trình) -> ghi manifest CSV.
    """
    cfg = load_config(config_path)
    # raw_dir lấy từ yaml; nếu yaml không có thì dùng "data/raw". Phép `/` giữa các Path là nối đường dẫn.
    raw_root = Path(cfg.get("raw_dir", "data/raw")) / cfg["city"]
    manifest = []                                       # mỗi file sẽ thêm một dòng vào đây
 
     
    # Với 4 mốc x 4 loại file, hai vòng lồng nhau chạy 16 lần.
    for snap in cfg["snapshots"]:
        for kind, spec in FILES.items():
            # Đường dẫn lưu: data/raw/new-york-city/2025-09-01/listings.csv.gz
            # Path(spec["rel"]).name bỏ phần thư mục "data/", chỉ lấy tên file.
            dest = raw_root / snap / Path(spec["rel"]).name
            url = build_url(cfg["data_root"], snap, spec["rel"])
 
            # Dòng ghi nhận cho file này (sau thành một dòng của download_manifest.csv).
            # Khai báo đủ các trường với giá trị rỗng, các nhánh bên dưới điền dần,
            # nên dù thành công hay thất bại, dòng nào cũng đủ cột.
            # Lưu ý: downloaded_at được đặt lúc tạo row, nên với file "skipped" nó là giờ của lần chạy này,
            # không phải giờ tải thật.
            row = {"snapshot": snap, "table": kind, "url": url, "path": str(dest),
                   "status": "", "http_status": None, "size_bytes": None, "sha256": None,
                   "downloaded_at": datetime.now(timezone.utc).isoformat(),
                   "message": ""}
            try:
                # Hướng 1: file đã có và không ép tải lại -> kiểm tra file cũ.
                if dest.exists() and not force:
                    try:
                        validate_file(dest, kind, snap)
                        row["status"] = "skipped"       # file cũ còn tốt: bỏ qua
                    except Exception:
                        # Lỗi ở đây KHÔNG phải thất bại, mà là tín hiệu "cần tải lại",
                        # nên bắt tại chỗ rồi xóa file hỏng.
                        log.warning("File cũ hỏng, tải lại: %s", dest)
                        dest.unlink()
                # Hướng 2: status vẫn là "" (chuỗi rỗng = sai) nghĩa là chưa xử lý xong
                # (file chưa có, bị ép tải lại, hoặc file cũ hỏng) -> tải mới.
                if not row["status"]:
                    log.info("Tải %s", url)
                    # SỬA: bản cũ viết `download_file(url.dest)` (dấu chấm). Hai đối số phải cách nhau bằng dấu phẩy.
                    download_file(url, dest)
                    validate_file(dest, kind, snap)
                    row["status"] = "ok"
                # Hai dòng này chạy cho cả "skipped" lẫn "ok".
                row["size_bytes"] = dest.stat().st_size  # kích thước tính bằng byte
                row["sha256"] = sha256_of(dest)
 
            # Thứ tự except KHÔNG được đảo: DownloadError là một loại Exception,
            # nếu đặt `except Exception` lên trước thì nhánh cụ thể này không bao giờ chạy.
            except DownloadError as e:
                # Lỗi HTTP (404, 403, 5xx đã hết lượt thử): có e.status để ghi vào cột http_status
                row["status"] = "failed"
                row["http_status"] = e.status
                row["message"] = str(e)
                log.error("%s/%s: %s", snap, kind, e)
            except Exception as e:
                # Mọi lỗi còn lại: file gzip hỏng, thiếu cột, lỗi ghi đĩa, lỗi mạng đã hết lượt...
                row["status"], row["message"] = "failed", str(e)
                log.error("%s/%s: %s", snap, kind, e)
            # Phải đặt trong vòng lặp trong, cùng cấp với `try`, để mọi file (ok / skipped / failed)
            # đều để lại đúng một dòng.
            manifest.append(row)
 
    # Ghi bảng tổng kết. Mỗi dict trong manifest thành một dòng, mỗi khóa thành một cột.
    # Lưu ý: file này bị ghi đè mỗi lần chạy, không cộng dồn.
    out = Path(cfg.get("reports_dir", "reports")) / "download_manifest.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(manifest).to_csv(out, index=False)     # index=False: bỏ cột số thứ tự
 
    failed = [m for m in manifest if m["status"] == "failed"]
    log.info("Xong: %d file, %d lỗi. Manifest: %s", len(manifest), len(failed), out)
    # Danh sách rỗng là "sai" nên trả 0 nếu không lỗi, 1 nếu có lỗi (quy ước shell: 0 = thành công).
    # Trả số thay vì tự gọi sys.exit để hàm dễ kiểm thử; sys.exit chỉ nằm ở khối 7.
    return 1 if failed else 0
 
# ── KHỐI 7: ĐIỂM VÀO ───────────────────────────────────────────────────────
# `__name__` bằng "__main__" khi chạy trực tiếp (python download.py ...), và bằng "download"
# khi file được import từ nơi khác (vd run_all.py). Nhờ vậy import không vô tình kích hoạt việc tải.
if __name__ == "__main__":
    # Cấu hình cách in log: chỉ in từ mức INFO trở lên; mỗi dòng gồm "MỨC nội dung".
    # Đây là chỗ quyết định logger "download" ở khối 2 in ra thế nào.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)           # bắt buộc: đường dẫn file yaml
    # store_true: là cờ bật/tắt, chỉ gõ --force (không kèm giá trị). Có gõ thì True, không gõ thì False.
    ap.add_argument("--force", action="store_true", help="tải lại dù file đã có")
    args = ap.parse_args()
    # run() trả 0 hoặc 1, sys.exit đưa số đó ra làm mã thoát để script khác biết bước tải có ổn không
    # (vd: python download.py ... && python qa.py chỉ chạy qa.py nếu tải không lỗi).
    sys.exit(run(args.config, args.force))