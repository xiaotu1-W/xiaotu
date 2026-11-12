"""信号控制器的公共骨架。

所有策略共用同一套「相位机」：
    绿灯 -> 黄灯 -> 全红 -> 下一相位绿灯 ...

策略只需要在绿灯结束时回答一个问题：**本相位绿灯还要不要再延长？**
（decide_extend），以及在相位切换时记录自己的决策统计。
这样固定配时、排队自适应、Webster 优化三种算法可以在同一个框架下公平对比。
"""

from __future__ import annotations

from dataclasses import dataclass, field


class PhaseState:
    GREEN = "green"
    YELLOW = "yellow"
    ALL_RED = "all_red"


@dataclass
class PhaseSnapshot:
    """控制器做决策时需要的路口状态快照（与仿真器解耦）。"""

    now: float
    queues: dict[int, int]              # 相位 -> 排队车辆数
    arrivals_15s: dict[int, int]        # 相位 -> 最近 15 秒到达车辆数
    last_green: dict[int, float]        # 相位 -> 上一轮实际绿灯时长
    last_cross: dict[int, float] = field(default_factory=dict)  # 相位 -> 最近一辆车越过停车线的时刻


class SignalController:
    """信号控制基类。

    子类需实现：
        name        策略名
        label       中文显示名
        min_green / max_green   绿灯上下限
        desired_green(phase, snap) -> 本相位期望绿灯时长（含延长）
    可选实现：
        on_phase_start(phase, snap)
        on_cycle_end(cycle_index)
    """

    name = "base"
    label = "基础信号"

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self.min_green = cfg.min_green
        self.max_green = cfg.max_green
        self.phase = 0
        self.state = PhaseState.GREEN
        self.state_timer = 0.0
        self.green_elapsed = 0.0
        self.green_planned = self.min_green
        self.stats: dict = {
            "green_total": 0.0,
            "phase_executions": 0,
            "extensions": 0,
            "shortened": 0,
            "per_phase_green": {0: [], 1: []},
            "cycle_lengths": [],
        }
        self._cycle_start = 0.0
        self.cycle_index = 0

    # ------------------------------------------------------------------
    # 子类接口
    # ------------------------------------------------------------------
    def desired_green(self, phase: int, snap: PhaseSnapshot) -> float:
        raise NotImplementedError

    def on_phase_start(self, phase: int, snap: PhaseSnapshot) -> None:
        """相位开始时调用，默认按最短绿灯起步。"""

    def on_cycle_end(self, cycle_index: int, cycle_length: float) -> None:
        self.stats["cycle_lengths"].append(cycle_length)

    # ------------------------------------------------------------------
    # 状态机
    # ------------------------------------------------------------------
    @property
    def phase_name(self) -> str:
        from config import PHASE_NAMES

        return PHASE_NAMES[self.phase]

    @property
    def display_color(self) -> str:
        """给渲染层用的灯色英文名。"""
        return self.state

    def update(self, dt: float, snap: PhaseSnapshot) -> None:
        """推进信号状态机。"""
        self.state_timer += dt

        if self.state == PhaseState.GREEN:
            self.green_elapsed += dt
            if self.green_elapsed >= self.green_planned:
                target = self._decide(snap)
                # target 是「期望的绿灯总时长」：大于已用时长 -> 延长；
                # 小于等于已用时长 -> 立即结束（gap-out / 固定配时到期）。
                if target > self.green_elapsed + 1e-6:
                    self.green_planned = target
                    self.stats["extensions"] += 1
                else:
                    self._finish_green(snap)
        elif self.state == PhaseState.YELLOW:
            if self.state_timer >= self.cfg.yellow_seconds:
                self._set_state(PhaseState.ALL_RED)
        elif self.state == PhaseState.ALL_RED:
            if self.state_timer >= self.cfg.all_red_seconds:
                self._next_phase(snap)

    def _decide(self, snap: PhaseSnapshot) -> float:
        probe = PhaseSnapshot(
            now=snap.now,
            queues=snap.queues,
            arrivals_15s=snap.arrivals_15s,
            last_green=snap.last_green,
            last_cross=snap.last_cross,
        )
        target = self.desired_green(self.phase, probe)
        return min(max(target, self.min_green), self.max_green)

    def _finish_green(self, snap: PhaseSnapshot) -> None:
        actual = self.green_elapsed
        self.stats["green_total"] += actual
        self.stats["phase_executions"] += 1
        self.stats["per_phase_green"][self.phase].append(actual)
        self.last_actual_green = actual
        self._set_state(PhaseState.YELLOW)

    def _next_phase(self, snap: PhaseSnapshot) -> None:
        self.phase = (self.phase + 1) % 2
        if self.phase == 0:
            # 回到相位 0 记为一个完整信号周期
            self.on_cycle_end(self.cycle_index, snap.now - self._cycle_start)
            self.cycle_index += 1
            self._cycle_start = snap.now
        self.green_elapsed = 0.0
        self.green_planned = min(self.max_green, max(self.min_green, self.initial_green(self.phase, snap)))
        self._set_state(PhaseState.GREEN)
        self.on_phase_start(self.phase, snap)

    def initial_green(self, phase: int, snap: PhaseSnapshot) -> float:
        """相位开始时的初始绿灯（默认最短绿灯，随后按需延长）。"""
        return self.min_green

    def _set_state(self, state: str) -> None:
        self.state = state
        self.state_timer = 0.0

    # ------------------------------------------------------------------
    # 对外信息
    # ------------------------------------------------------------------
    def info(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "phase": self.phase,
            "phase_name": self.phase_name,
            "state": self.state,
            "green_elapsed": self.green_elapsed,
            "green_planned": self.green_planned,
            "state_timer": self.state_timer,
        }
