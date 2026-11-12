"""图表导出（matplotlib）。

生成两类图：
1. 对比柱状图 —— 不同策略在同一车流量下的平均等待 / 吞吐量对比；
2. 时间序列 —— 排队长度随时间变化，直观展示信号切换过程。

中文显示：自动探测系统中文字体（微软雅黑 / 黑体 / 宋体），找不到则退回英文。
"""

from __future__ import annotations

import os

import matplotlib

matplotlib.use("Agg")                      # 无界面后端，可在服务器/CI 上跑
import matplotlib.pyplot as plt
from matplotlib import font_manager


def _setup_font() -> None:
    """配置中文字体。"""
    candidates = ["Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei"]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False


_setup_font()

STRATEGY_LABELS = {"fixed": "固定配时", "actuated": "自适应配时", "webster": "Webster 优化"}
STRATEGY_COLORS = {"fixed": "#818CF8", "actuated": "#2DD4BF", "webster": "#FACC15"}


def bar_compare(results: list[dict], key: str, title: str, ylabel: str, path: str,
                key_label_map: dict[str, str] | None = None) -> str:
    """横向柱状图：多个策略对比某一指标。

    results: [{strategy, metrics...}, ...]
    key:     要对比的指标名（如 "mean_wait"）
    """
    strategies = [r["strategy"] for r in results]
    values = [r.get(key, 0.0) for r in results]
    labels = [STRATEGY_LABELS.get(s, s) for s in strategies]
    colors = [STRATEGY_COLORS.get(s, "#64748B") for s in strategies]

    fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=130)
    bars = ax.bar(labels, values, color=colors, width=0.55)
    for b, v in zip(bars, values):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:g}",
                ha="center", va="bottom", fontsize=10, color="#334155")
    ax.set_title(title, fontsize=13, pad=12)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    fig.tight_layout()
    _save(fig, path)
    return path


def grouped_bar(results_by_demand: dict[float, list[dict]], key: str, title: str, ylabel: str, path: str) -> str:
    """分组柱状图：x 轴为车流量，每组对比多个策略。"""
    demands = sorted(results_by_demand)
    strategies = sorted({r["strategy"] for rs in results_by_demand.values() for r in rs})
    n = len(strategies)
    import numpy as np

    x = np.arange(len(demands))
    width = 0.8 / max(n, 1)
    fig, ax = plt.subplots(figsize=(8.2, 4.0), dpi=130)
    for i, s in enumerate(strategies):
        vals = []
        for d in demands:
            row = next((r for r in results_by_demand[d] if r["strategy"] == s), None)
            vals.append(row.get(key, 0.0) if row else 0.0)
        ax.bar(x + (i - (n - 1) / 2) * width, vals, width, label=STRATEGY_LABELS.get(s, s),
               color=STRATEGY_COLORS.get(s, "#64748B"))
    ax.set_xticks(x)
    ax.set_xticklabels([f"{int(d)}" for d in demands])
    ax.set_xlabel("单进口道车流量 (辆/小时)", fontsize=11)
    ax.set_ylabel(ylabel, fontsize=11)
    ax.set_title(title, fontsize=13, pad=12)
    ax.legend(frameon=False, ncol=n)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25, linewidth=0.6)
    fig.tight_layout()
    _save(fig, path)
    return path


def timeseries(series: dict, path: str, title: str = "", smooth: int = 1) -> str:
    """排队长度时间序列。"""
    t = series["t"]
    ns = series.get("queue_ns", [])
    ew = series.get("queue_ew", [])
    fig, ax = plt.subplots(figsize=(8.5, 3.4), dpi=130)
    if smooth > 1 and len(t) > smooth:
        def _mv(x, w):
            out = []
            for i in range(len(x)):
                s = x[max(0, i - w + 1): i + 1]
                out.append(sum(s) / len(s))
            return out
        ns = _mv(ns, smooth)
        ew = _mv(ew, smooth)
    ax.plot(t, ns, color="#2DD4BF", label="南北相位排队", linewidth=1.4)
    ax.plot(t, ew, color="#F59E0B", label="东西相位排队", linewidth=1.4)
    ax.set_xlabel("仿真时间 (秒)", fontsize=11)
    ax.set_ylabel("排队车辆数", fontsize=11)
    if title:
        ax.set_title(title, fontsize=13, pad=12)
    ax.legend(frameon=False, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=0.25, linewidth=0.6)
    fig.tight_layout()
    _save(fig, path)
    return path


def _save(fig, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return path
