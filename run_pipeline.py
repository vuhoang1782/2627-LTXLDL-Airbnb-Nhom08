"""Chạy toàn bộ quy trình bằng MỘT lệnh:

    python run_pipeline.py --config configs/new_york_city.yaml

Tuỳ chọn: --steps download,subset,...  --skip-download  --skip-llm  --llm-limit N  --make-label-template
"""
from __future__ import annotations

import argparse
import time

from src.utils import get_logger, load_config

STEPS = ["download", "subset", "check", "qa", "llm", "baseline", "evaluate", "kpi", "viz"]
log = get_logger("pipeline")


def run_step(name, cfg, args):
    if name == "download":
        from src import download
        download.run(cfg)
    elif name == "subset":
        from src import subset
        subset.run(cfg)
    elif name == "check":
        from src import check_report
        check_report.run(cfg)
    elif name == "qa":
        from src import qa
        qa.run(cfg)
    elif name == "llm":
        from src import llm
        llm.run(cfg, skip_llm=args.skip_llm, limit=args.llm_limit)
    elif name == "baseline":
        from src import baseline
        baseline.run(cfg, limit=args.llm_limit)
    elif name == "evaluate":
        from src import evaluate
        evaluate.run(cfg)
    elif name == "kpi":
        from src import kpi
        kpi.run(cfg)
    elif name == "viz":
        from src import viz
        viz.run(cfg)


def main():
    ap = argparse.ArgumentParser(description="Quy trình phân tích Inside Airbnb")
    ap.add_argument("--config", required=True, help="vd. configs/new_york_city.yaml")
    ap.add_argument("--steps", default=",".join(STEPS), help="danh sách bước, ngăn cách bằng dấu phẩy")
    ap.add_argument("--skip-download", action="store_true", help="bỏ qua bước tải (đã có data/raw)")
    ap.add_argument("--skip-llm", action="store_true", help="không gọi API LLM, chỉ dùng cache")
    ap.add_argument("--llm-limit", type=int, default=None, help="chỉ xử lý N review đầu (chạy thử)")
    ap.add_argument("--make-label-template", action="store_true", help="tạo tệp mẫu gán nhãn tay rồi thoát")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.make_label_template:
        from src import evaluate
        evaluate.run(cfg, template_only=True)
        return
    steps = [s.strip() for s in args.steps.split(",") if s.strip()]
    if args.skip_download and "download" in steps:
        steps.remove("download")
    unknown = [s for s in steps if s not in STEPS]
    if unknown:
        raise SystemExit(f"Bước không hợp lệ: {unknown}. Hợp lệ: {STEPS}")
    for name in steps:
        t0 = time.time()
        log.info("===== BƯỚC: %s =====", name)
        run_step(name, cfg, args)
        log.info("Xong %s (%.1fs)", name, time.time() - t0)


if __name__ == "__main__":
    main()
