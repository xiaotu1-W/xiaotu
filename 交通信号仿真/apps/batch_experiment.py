"""批量对比实验。

    python -m apps.batch_experiment                    # 完整实验
    python -m apps.batch_experiment --quick            # 短仿真快速验证
    python -m apps.batch_experiment --no-save          # 不写数据库
    python -m apps.batch_experiment --no-charts        # 不生成图表

实验设计（三组场景，覆盖自适应配时的三种典型工况）
----------------------------------------------------
1. 均衡场景 —— 四进口道车流相等：固定配时已接近最优，自适应/Webster 仅靠
   「缩短周期」小幅改善；
2. 主次不均衡场景 —— 南北为主干道、东西为次干道：Webster 按已知需求精确
   分配绿灯（绿信比），优势最大；
3. 潮汐车流场景 —— 需求随时间在「南北多 / 东西多 / 均衡」之间切换：只有
   自适应配时能实时跟踪波动，固定配时与 Webster（按平均需求计算）都会失配。

结论：需求已知且稳定 -> Webster 最优；需求未知或时变 -> 自适应最优。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import SimConfig, project_path
from engine import Simulation
from controllers.strategies import STRATEGIES

# 稳态场景：名字 -> 东西/南北需求比
STEADY_SCENARIOS = [
    ("均衡", 1.0),
    ("主次不均衡", 0.3),
]


def tidal_config() -> dict:
    """潮汐车流：早高峰南北多 → 晚高峰东西多 → 平峰均衡。

    三段各占 1/3，时间平均后南北 = 东西 = 540 vph，即「平均是均衡的」，
    因此 Webster（按平均需求离线计算）和固定配时都会在每一段失配。
    """
    return dict(
        demand_vph=540.0,
        demand_ratio_ew=1.0,
        demand_profile=(
            (0.0, 900.0, 0.3),        # 早高峰：南北 900、东西 270
            (700.0, 270.0, 3.333),    # 晚高峰：南北 270、东西 900
            (1400.0, 450.0, 1.0),     # 平峰：双向 450
        ),
    )


def run_one(demand: float, strategy: str, warmup: float, measure: float, ratio: float,
            profile: tuple = ()) -> dict:
    cfg = SimConfig(demand_vph=demand, demand_ratio_ew=ratio, demand_profile=profile,
                    warmup_seconds=warmup, measure_seconds=measure)
    sim = Simulation(cfg, strategy)
    res = sim.run()
    return {**res.metrics, "config": cfg.to_dict(), "controller": res.controller_stats}


def _print_row(demand: float, strategy: str, row: dict, dt: float) -> None:
    print(
        f"  车流 {int(demand):4d} vph | {STRATEGIES[strategy]:6s} | "
        f"平均等待 {row['mean_wait']:6.2f}s | P95 {row['p95_wait']:6.2f}s | "
        f"吞吐 {row['throughput_vph']:6.1f} | 最大排队 {row['max_queue']:3d} | "
        f"南北绿灯 {row['green_ns_mean']:5.1f}s / 东西 {row['green_ew_mean']:5.1f}s | ({dt:.1f}s)"
    )


def _report_improvement(by_demand: dict[float, list[dict]], demands: list[float]) -> None:
    print("  相对「固定配时」的改善（负值 = 降低，即更好）：")
    for demand in demands:
        base = next(r for r in by_demand[demand] if r["strategy"] == "fixed")
        parts = []
        for r in by_demand[demand]:
            if r["strategy"] == "fixed":
                continue
            d_wait = (r["mean_wait"] - base["mean_wait"]) / base["mean_wait"] * 100
            d_queue = (r["max_queue"] - base["max_queue"]) / max(base["max_queue"], 1) * 100
            parts.append(f"{STRATEGIES[r['strategy']]}: 等待{d_wait:+.1f}% 排队{d_queue:+.1f}%")
        print(f"    车流 {int(demand):4d} vph → " + " | ".join(parts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="交通信号配时仿真批量实验")
    parser.add_argument("--demand", type=float, nargs="+", default=[300, 500, 700, 900])
    parser.add_argument("--strategies", nargs="+", default=["fixed", "actuated", "webster"], choices=list(STRATEGIES))
    parser.add_argument("--ratio", type=float, default=None, help="只跑一个稳态不均衡比")
    parser.add_argument("--quick", action="store_true", help="短仿真快速验证")
    parser.add_argument("--no-save", action="store_true", help="不写入数据库")
    parser.add_argument("--no-charts", action="store_true", help="不生成图表")
    parser.add_argument("--out", default="results", help="图表输出目录")
    args = parser.parse_args(argv)

    warmup = 120.0 if args.quick else 300.0
    measure = 300.0 if args.quick else 1800.0
    steady = STEADY_SCENARIOS if args.ratio is None else [("不均衡", args.ratio)]

    from storage import StrategyRepository

    repo = None if args.no_save else StrategyRepository()

    print("=" * 82)
    print(f"批量实验：策略 {args.strategies}，统计期 {int(measure)}s")
    print("=" * 82)

    all_summary: dict[str, dict] = {}

    # ------------------------------------------------------------------
    # 1 & 2. 稳态场景（均衡 / 不均衡）
    # ------------------------------------------------------------------
    for scenario_name, ratio in steady:
        print(f"\n【场景】{scenario_name}（东西向/南北向 = {ratio:g}）")
        print("-" * 82)
        by_demand: dict[float, list[dict]] = {}
        for demand in args.demand:
            by_demand[demand] = []
            for strategy in args.strategies:
                t0 = time.perf_counter()
                row = run_one(demand, strategy, warmup, measure, ratio)
                dt = time.perf_counter() - t0
                by_demand[demand].append(row)
                if repo is not None:
                    repo.insert_run(strategy, SimConfig(demand_vph=demand, demand_ratio_ew=ratio), row, row["controller"])
                _print_row(demand, strategy, row, dt)
        all_summary[scenario_name] = {int(d): by_demand[d] for d in args.demand}
        _report_improvement(by_demand, args.demand)

    # ------------------------------------------------------------------
    # 3. 潮汐车流（时变需求）
    # ------------------------------------------------------------------
    print("\n【场景】潮汐车流（早高峰南北多 → 晚高峰东西多 → 平峰均衡，时变需求）")
    print("-" * 82)
    tidal: list[dict] = []
    for strategy in args.strategies:
        t0 = time.perf_counter()
        cfg_kwargs = tidal_config()
        cfg = SimConfig(warmup_seconds=warmup, measure_seconds=measure, **cfg_kwargs)
        sim = Simulation(cfg, strategy)
        res = sim.run()
        row = {**res.metrics, "config": cfg.to_dict(), "controller": res.controller_stats}
        dt = time.perf_counter() - t0
        tidal.append(row)
        if repo is not None:
            repo.insert_run(strategy, cfg, row, row["controller"])
        _print_row(540, strategy, row, dt)
    all_summary["潮汐车流"] = {540: tidal}
    # 以固定配时为基准报告改善
    base = next(r for r in tidal if r["strategy"] == "fixed")
    print("  相对「固定配时」的改善：")
    for r in tidal:
        if r["strategy"] == "fixed":
            continue
        d_wait = (r["mean_wait"] - base["mean_wait"]) / base["mean_wait"] * 100
        print(f"    {STRATEGIES[r['strategy']]}: 平均等待 {d_wait:+.1f}%")

    if repo is not None:
        repo.close()

    # ------------------------------------------------------------------
    # 图表
    # ------------------------------------------------------------------
    if not args.no_charts:
        out_dir = project_path(args.out)
        os.makedirs(out_dir, exist_ok=True)
        import charts

        for scenario_name, _ in steady:
            by_demand = all_summary[scenario_name]
            tag = "balanced" if scenario_name == "均衡" else "imbalanced"
            for key, title, ylabel, fname in [
                ("mean_wait", "平均等待时间对比", "平均等待 (秒/辆)", "mean_wait"),
                ("throughput_vph", "路口吞吐量对比", "吞吐量 (辆/小时)", "throughput"),
                ("max_queue", "最大排队长度对比", "最大排队 (辆)", "max_queue"),
            ]:
                charts.grouped_bar(by_demand, key, f"{scenario_name}场景 · {title}", ylabel,
                                   os.path.join(out_dir, f"{tag}_{fname}.png"))
        # 潮汐场景时间序列（排队 + 信号，最能体现自适应跟踪）
        for strategy in args.strategies:
            cfg = SimConfig(warmup_seconds=warmup, measure_seconds=measure, **tidal_config())
            sim = Simulation(cfg, strategy)
            sim.run()
            charts.timeseries(
                sim.series,
                os.path.join(out_dir, f"tidal_{strategy}.png"),
                title=f"{STRATEGIES[strategy]} · 潮汐车流排队变化",
                smooth=10,
            )
        with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as f:
            json.dump(all_summary, f, ensure_ascii=False, indent=2)
        print(f"\n图表已导出到: {out_dir}")

    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
