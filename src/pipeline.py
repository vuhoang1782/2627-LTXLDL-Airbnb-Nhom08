"""Chạy toàn bộ quy trình bằng một lệnh:  python -m src.pipeline --config configs/new_york_city.yaml [--skip-llm]

Thứ tự: tải -> QA (trước LLM) -> LLM -> baseline -> QA10 (sau LLM) -> KPI -> hình -> chấm điểm.
Chấm điểm đặt cuối: thiếu nhãn tay thì chỉ cảnh báo, các sản phẩm khác đã xong.
--skip-llm: không gọi API, chỉ dùng kết quả LLM đã cache (không cần khoá API).
"""
from src import baseline, download, evaluate, kpi, llm, qa, viz
from src.utils import cli, get_logger

log = get_logger("pipeline")
STEPS = [("download", download.main, {}), ("qa", qa.main, {}), ("llm", llm.main, {"skip_llm": True}),
         ("baseline", baseline.main, {}), ("qa --post", qa.main, {"post": True}), ("kpi", kpi.main, {}),
         ("viz", viz.main, {}), ("evaluate", evaluate.main, {})]


def main(cfg, skip_llm=False):
    for name, step, fixed in STEPS:
        log.info("=== %s ===", name)
        kw = {k: (skip_llm if k == "skip_llm" else v) for k, v in fixed.items()}
        step(cfg, **kw)


if __name__ == "__main__":
    cli(main)
