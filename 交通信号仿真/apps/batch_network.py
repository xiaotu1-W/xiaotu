"""多路口网格批量实验 CLI（支持并行加速 + 进度显示）。

对比「独立配时 vs 绿波协调」在多个网格尺寸、不同方向偏置下的表现，
并汇总成表格 + 可选的 HTML 报告。

用法：
    python -m apps.batch_network                        # 默认组合
    python -m apps.batch_network --grid 2x2 3x3         # 指定网格
    python -m apps.batch_network --lite                 # 短仿真快速验证
    python -m apps.batch_network --bias 2.0 3.0         # 方向偏置系数
    python -m apps.batch_network --jobs 8               # 并行进程数（0=自动）
    python -m apps.batch_network --html                 # 同时生成 HTML 报告

并行说明：每个「网格 × 偏置 × 模式」组合互相独立，用进程池并行执行，
核数越多越快；`--jobs 1` 可退回串行（便于调试）。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import SimConfig
from engine_network import NetworkSimulation


def parse_grid(s: str) -> tuple[int, int]:
    a, b = s.lower().split("x")
    return int(a), int(b)


def _run_task(task: dict) -> dict:
    """执行一次网格仿真（独立进程内），返回纯 dict 结果。"""
    cfg = SimConfig(demand_vph=task["demand"], warmup_seconds=task["warmup"],
                    measure_seconds=task["measure"], seed=7)
    sim = NetworkSimulation(
        cfg, rows=task["rows"], cols=task["cols"], link_length=task["link"],
        strategy="fixed", coordinated=task["coordinated"],
        direction_bias=3, bias_factor=task["bias"],
    )
    r = sim.run()
    return {
        "rows": task["rows"], "cols": task["cols"], "bias": task["bias"],
        "coordinated": task["coordinated"],
        "mean_wait": r["mean_wait"], "max_queue": r["max_queue"],
        "throughput_vph": r["throughput_vph"], "departed": r["departed"],
    }


def _progress(done: int, total: int, t0: float, label: str) -> None:
    pct = done / total * 100 if total else 100.0
    elapsed = time.perf_counter() - t0
    eta = (elapsed / done * (total - done)) if done else 0.0
    bar_len = 24
    filled = int(bar_len * done / total) if total else bar_len
    bar = "█" * filled + "░" * (bar_len - filled)
    print(f"\r  [{bar}] {pct:5.1f}%  {done}/{total}  {label:<22} 已用 {elapsed:5.1f}s 预计剩余 {eta:5.1f}s",
          end="", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="多路口网格绿波协调批量实验")
    parser.add_argument("--grid", nargs="+", default=["2x2", "3x3"])
    parser.add_argument("--bias", type=float, nargs="+", default=[3.0])
    parser.add_argument("--link", type=float, default=220.0)
    parser.add_argument("--demand", type=float, default=700.0)
    parser.add_argument("--lite", action="store_true")
    parser.add_argument("--jobs", type=int, default=0, help="并行进程数，0=自动（CPU 核数）")
    parser.add_argument("--html", action="store_true", help="同时生成 HTML 报告")
    args = parser.parse_args(argv)

    warmup = 60 if args.lite else 180
    measure = 120 if args.lite else 360
    grids = [parse_grid(g) for g in args.grid]

    # 组装任务：每个 (网格, 偏置, 模式) 一次仿真
    tasks: list[dict] = []
    for rows, cols in grids:
        for bias in args.bias:
            for coord in (False, True):
                tasks.append({
                    "rows": rows, "cols": cols, "link": args.link, "demand": args.demand,
                    "warmup": warmup, "measure": measure, "bias": bias, "coordinated": coord,
                })

    jobs = args.jobs if args.jobs > 0 else (os.cpu_count() or 1)
    jobs = max(1, min(jobs, len(tasks)))

    print("=" * 82)
    print(f"多路口网格绿波协调实验：统计期 {int(measure)}s，方向偏置 {args.bias}，"
          f"共 {len(tasks)} 次仿真，并行 {jobs} 进程")
    print("=" * 82)

    t0 = time.perf_counter()
    results: list[dict] = []
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor, as_completed

        with ProcessPoolExecutor(max_workers=jobs) as ex:
            futures = {ex.submit(_run_task, t): t for t in tasks}
            for i, fut in enumerate(as_completed(futures), 1):
                results.append(fut.result())
                t = futures[fut]
                label = f"{t['rows']}x{t['cols']} bias{t['bias']:g} {'协调' if t['coordinated'] else '独立'}"
                _progress(i, len(tasks), t0, label)
    else:
        for i, t in enumerate(tasks, 1):
            results.append(_run_task(t))
            label = f"{t['rows']}x{t['cols']} bias{t['bias']:g} {'协调' if t['coordinated'] else '独立'}"
            _progress(i, len(tasks), t0, label)
    print()
    total_time = time.perf_counter() - t0
    print(f"全部完成，用时 {total_time:.1f}s（平均 {total_time/len(tasks):.1f}s/次）\n")

    # 按 (网格, 偏置) 汇总成表
    header = (f"{'网格':>6} | {'偏置':>4} | {'独立·等待':>10} | {'协调·等待':>10} | {'改善':>7} | "
              f"{'独立·排队':>9} | {'协调·排队':>9} | {'独立·吞吐':>9} | {'协调·吞吐':>9}")
    print(header)
    print("-" * len(header))

    for rows, cols in grids:
        for bias in args.bias:
            r0 = next((r for r in results if r["rows"] == rows and r["cols"] == cols
                       and r["bias"] == bias and not r["coordinated"]), None)
            r1 = next((r for r in results if r["rows"] == rows and r["cols"] == cols
                       and r["bias"] == bias and r["coordinated"]), None)
            if not r0 or not r1:
                continue
            d = (r1["mean_wait"] - r0["mean_wait"]) / r0["mean_wait"] * 100
            print(f"{rows}x{cols:<3} | {bias:>4g} | {r0['mean_wait']:>10.2f} | {r1['mean_wait']:>10.2f} | "
                  f"{d:>+6.1f}% | {r0['max_queue']:>9d} | {r1['max_queue']:>9d} | "
                  f"{r0['throughput_vph']:>9.0f} | {r1['throughput_vph']:>9.0f}")

    print("\n结论要点：")
    print("  * 方向偏置越大（单向潮汐主干道越明显），绿波协调改善越显著；")
    print("  * 双向均衡车流下，固定绿波优化一个方向会牺牲另一方向，改善有限甚至为负；")
    print("  * 这是绿波协调的固有特征：无方向的均衡车流更适合自适应配时或 Webster 优化。")

    if args.html:
        from apps.html_report import run_comparison, build_html
        from config import project_path

        for rows, cols in grids:
            comp = run_comparison(rows, cols, args.link, args.lite)
            html = build_html(comp)
            out = project_path(f"report/report_{rows}x{cols}.html")
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                f.write(html)
            print(f"\nHTML 报告: {out}")

    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
