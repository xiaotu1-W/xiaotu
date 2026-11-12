"""交通评价指标。

指标体系参照《城市道路信号交叉口通行能力与服务水平》(HCM) 常用口径：
* 平均延误 / 平均等待时间（秒/辆）—— 服务水平的核心指标；
* 95 分位等待时间（秒）—— 反映长尾体验，均值掩盖的极端排队；
* 最大排队长度（辆）、平均排队（辆）—— 排队溢出风险；
* 吞吐量（辆/小时）—— 实际通行能力；
* 服务率 = 驶离车辆 / 到达车辆 —— 衡量是否过饱和；
* 平均停车次数 —— 车辆走走停停程度，关联油耗与排放。

等待时间的定义：车辆以「排队」状态（速度<0.8m/s 且被前车或红灯挡住）
持续 0.5 秒以上开始计时，直到重新启动为止，累加得到单车的排队等待时长。
只统计统计期内到达并驶离的车辆。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from engine import Simulation


def percentile(values: list[float], p: float) -> float:
    """线性插值分位数（与 numpy.percentile 默认口径一致）。"""
    if not values:
        return 0.0
    data = sorted(values)
    if len(data) == 1:
        return float(data[0])
    k = (len(data) - 1) * p / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(data[lo])
    return float(data[lo] + (data[hi] - data[lo]) * (k - lo))


def compute_metrics(sim: "Simulation") -> dict:
    cfg = sim.cfg
    window = cfg.measure_seconds
    waits = [d["wait"] for d in sim.departed]
    n_departed = len(waits)
    throughput = n_departed * 3600.0 / window if window > 0 else 0.0
    arrival_rate = sim.spawned_measured * 3600.0 / window if window > 0 else 0.0

    mean_queue = 0.0
    total_samples = sum(st["queue_samples"] for st in sim.lane_stats.values())
    if total_samples:
        mean_queue = sum(st["queue_sum"] for st in sim.lane_stats.values()) / total_samples

    wait_sum = sum(waits)
    metrics = {
        # 基础
        "strategy": sim.strategy,
        "demand_vph": cfg.demand_vph,
        "arrivals": sim.spawned_measured,
        "departed": n_departed,
        "throughput_vph": round(throughput, 1),
        "arrival_rate_vph": round(arrival_rate, 1),
        "service_ratio": round(n_departed / sim.spawned_measured, 4) if sim.spawned_measured else 0.0,
        # 延误
        "mean_wait": round(wait_sum / n_departed, 2) if n_departed else 0.0,
        "p95_wait": round(percentile(waits, 95), 2),
        "max_wait": round(max(waits), 2) if waits else 0.0,
        "total_wait_hours": round(wait_sum / 3600.0, 3),
        # 排队
        "max_queue": int(sim.max_queue),
        "mean_queue": round(mean_queue, 2),
        "queue_overflow": int(sim.max_queue >= cfg.storage_capacity),
        # 信号
        "vc_ratio": round(cfg.saturation_ratio, 3),
    }
    metrics.update(summarise_controller(sim.controller))
    return metrics


def summarise_controller(controller) -> dict:
    stats = controller.stats
    greens = stats["per_phase_green"]
    all_greens = greens[0] + greens[1]
    cycles = stats["cycle_lengths"]
    mean_queue_trace = 0.0
    trace = stats.get("queue_trace") or []
    if trace:
        mean_queue_trace = sum(a + b for _, a, b in trace) / (2.0 * len(trace))
    return {
        "phase_executions": stats["phase_executions"],
        "green_total": round(stats["green_total"], 1),
        "mean_green": round(sum(all_greens) / len(all_greens), 2) if all_greens else 0.0,
        "green_ns_mean": round(sum(greens[0]) / len(greens[0]), 2) if greens[0] else 0.0,
        "green_ew_mean": round(sum(greens[1]) / len(greens[1]), 2) if greens[1] else 0.0,
        "extensions": stats["extensions"],
        "mean_cycle": round(sum(cycles) / len(cycles), 2) if cycles else 0.0,
        "min_cycle": round(min(cycles), 2) if cycles else 0.0,
        "max_cycle": round(max(cycles), 2) if cycles else 0.0,
        "mean_queue_control": round(mean_queue_trace, 2),
    }


def compare(results: list[dict]) -> dict:
    """以「第一个策略」为基准，计算其余策略的相对改善。

    返回 {strategy: {"mean_wait": -23.5, "max_queue": ..., ...}}
    负数表示指标下降。只比较同时存在的策略。
    """
    if not results:
        return {}
    base = results[0]
    out: dict[str, dict] = {}
    for res in results[1:]:
        delta = {}
        for key in ("mean_wait", "p95_wait", "max_queue", "mean_queue", "throughput_vph", "service_ratio"):
            b = base.get(key, 0.0)
            r = res.get(key, 0.0)
            delta[key] = round((r - b) / b * 100.0, 2) if b else 0.0
        out[res["strategy"]] = delta
    return out
