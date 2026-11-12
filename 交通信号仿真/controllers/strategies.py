"""三种信号配时策略。

1. FixedTimeController —— 固定配时（传统定时红绿灯）
2. ActuatedController  —— 基于排队长度的感应式自适应配时
3. WebsterController   —— 基于 Webster 最优周期的离线优化配时

三种策略共用 controllers.base.SignalController 的相位状态机，
公平性体现在：同一路口、同一车流、同一随机种子、同一最短/最长绿灯约束。
"""

from __future__ import annotations

import math

from config import SimConfig
from controllers.base import PhaseSnapshot, SignalController


# --------------------------------------------------------------------------
# 1. 固定配时
# --------------------------------------------------------------------------
class FixedTimeController(SignalController):
    """固定配时：每个相位绿灯时长恒定，与路口实际车流无关。"""

    name = "fixed"
    label = "固定配时"

    def __init__(self, cfg: SimConfig, green: float | None = None) -> None:
        super().__init__(cfg)
        self.green = float(green if green is not None else cfg.fixed_green)
        self.min_green = self.green
        self.max_green = self.green
        self.green_planned = self.green

    def initial_green(self, phase: int, snap: PhaseSnapshot) -> float:
        return self.green

    def desired_green(self, phase: int, snap: PhaseSnapshot) -> float:
        return self.green


# --------------------------------------------------------------------------
# 2. 基于排队长度的感应式自适应配时
# --------------------------------------------------------------------------
class ActuatedController(SignalController):
    """基于排队长度的感应式（actuated）自适应配时。

    算法（经典 queue-actuated / gap-out 控制）：
    * 每个相位以最短绿灯起步；
    * 绿灯期间每 1 秒评估一次：只要仍有车辆持续越过停车线（车流未断），
      就延长 1 秒，直到最长绿灯；
    * 若连续 gap_out 秒没有车辆越过停车线（车流出现空档），立即结束绿灯
      并把剩余时间让给另一方向；
    * 公平性兜底：某相位在红灯期间持续排队超过 max_wait 秒则强制切换。

    与固定配时的本质区别：绿灯时长不是写死的，而是由实时车流反馈决定——
    车流大则绿灯长（延至上限），车流小则绿灯短（提前结束），
    车流不均衡或随时间波动时能自动把绿灯让给更拥堵的方向。
    """

    name = "actuated"
    label = "自适应配时"

    def __init__(
        self,
        cfg: SimConfig,
        gap_out: float = 3.0,
        decision_step: float = 1.0,
        max_wait: float = 120.0,
    ) -> None:
        super().__init__(cfg)
        self.gap_out = gap_out
        self.decision_step = decision_step
        self.max_wait = max_wait
        self.stats["queue_trace"] = []
        self._queue_since: dict[int, float | None] = {0: None, 1: None}

    def initial_green(self, phase: int, snap: PhaseSnapshot) -> float:
        return self.min_green

    def desired_green(self, phase: int, snap: PhaseSnapshot) -> float:
        elapsed = self.green_elapsed
        other = 1 - phase

        # ① 公平性：另一相位红灯排队等待超时 -> 让行
        since = self._queue_since.get(other)
        if since is not None and snap.now - since >= self.max_wait:
            return elapsed
        # ② gap-out：车流出现空档（最近 gap_out 秒无车越过停车线）-> 结束
        last = snap.last_cross.get(phase, -1e9)
        if snap.now - last > self.gap_out:
            return elapsed
        # ③ 仍有车流持续通过 -> 延长绿灯
        return elapsed + self.decision_step

    def update(self, dt: float, snap: PhaseSnapshot) -> None:
        self.stats["queue_trace"].append((snap.now, int(snap.queues.get(0, 0)), int(snap.queues.get(1, 0))))
        # 维护各相位「红灯期间排队起始时刻」用于公平性判定
        for p in (0, 1):
            if snap.queues.get(p, 0) > 0 and p != self.phase:
                if self._queue_since[p] is None:
                    self._queue_since[p] = snap.now
            else:
                self._queue_since[p] = None
        super().update(dt, snap)


# --------------------------------------------------------------------------
# 3. Webster 离线优化配时
# --------------------------------------------------------------------------
def webster_split(
    flows: dict[int, float],
    saturation_flow: float,
    lost_time: float = 8.0,
    min_cycle: float = 30.0,
    max_cycle: float = 120.0,
) -> tuple[float, dict[int, float]]:
    """Webster 最优周期与有效绿灯分配。

    flows: 相位 -> 关键车流率（辆/小时）
    返回 (周期, {相位: 有效绿灯秒数})。
    """
    y = {p: min(0.95, f / saturation_flow) for p, f in flows.items()}
    y_sum = sum(y.values())
    if y_sum >= 1.0:
        # 过饱和：直接取最大周期
        cycle = max_cycle
    else:
        c0 = (1.5 * lost_time + 5.0) / (1.0 - y_sum)
        cycle = min(max(c0, min_cycle), max_cycle)
    effective = max(cycle - lost_time, 4.0)
    total_y = y_sum or 1.0
    return cycle, {p: effective * y[p] / total_y for p in flows}


class WebsterController(SignalController):
    """基于 Webster 最优周期的离线优化配时。

    Webster 公式给出的周期是「使平均延误会最小」的经典交通工程结果：
        C0 = (1.5L + 5) / (1 - Y)
    这里用**稳态需求**（而非实时排队）计算周期与绿信比，属于离线优化的
    开环控制，作为「有模型依据的固定配时」与另两种策略对比。
    """

    name = "webster"
    label = "Webster 优化"

    def __init__(self, cfg: SimConfig, extra_lost: float = 0.0) -> None:
        super().__init__(cfg)
        lost = 2 * (cfg.yellow_seconds + cfg.all_red_seconds) + extra_lost
        # 两个相位的关键车道流量：直行车道是各相位最繁忙（关键）车道。
        # 南北相位关键流量 = 南北进口道（二者中较忙者）直行到达率；
        # 东西相位关键流量 = 东西进口道直行到达率。
        ns_flow = cfg.demand_vph * cfg.through_ratio
        ew_flow = cfg.direction_demand(1) * cfg.through_ratio
        self.cycle, split = webster_split(
            {0: ns_flow, 1: ew_flow},
            saturation_flow=cfg.capacity_vph,
            lost_time=lost,
            min_cycle=cfg.min_green * 2 + lost,
            max_cycle=max(cfg.max_green * 2 + lost, 90.0),
        )
        self.split = split
        self.green_plan = {p: max(cfg.min_green, min(cfg.max_green, split[p])) for p in (0, 1)}
        self.min_green = min(self.green_plan.values())
        self.max_green = max(self.green_plan.values())
        self.green_planned = self.green_plan[0]

    def initial_green(self, phase: int, snap: PhaseSnapshot) -> float:
        return self.green_plan[phase]

    def desired_green(self, phase: int, snap: PhaseSnapshot) -> float:
        return self.green_plan[phase]


# --------------------------------------------------------------------------
# 工厂
# --------------------------------------------------------------------------
def create_controller(name: str, cfg: SimConfig) -> SignalController:
    mapping = {
        "fixed": lambda: FixedTimeController(cfg),
        "actuated": lambda: ActuatedController(cfg),
        "webster": lambda: WebsterController(cfg),
    }
    if name not in mapping:
        raise KeyError(f"未知控制策略: {name}，可选 {list(mapping)}")
    return mapping[name]()


STRATEGIES = {
    "fixed": FixedTimeController.label,
    "actuated": ActuatedController.label,
    "webster": WebsterController.label,
}

__all__ = [
    "FixedTimeController",
    "ActuatedController",
    "WebsterController",
    "create_controller",
    "webster_split",
    "STRATEGIES",
    "math",
]
