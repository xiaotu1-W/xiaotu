"""绿波协调信号控制器。

在单路口三类信号策略之上，增加「路网级协调」：所有路口共享同一公共周期，
每个路口按「相位差 offset」平移自己的相位时钟，使东西向主干道车流沿绿波
方向连续通过（下游绿灯相对上游延后一个路段的行驶时间）。

实现：把绝对时间映射到相位状态。控制器不再依赖 base.SignalController 的
增量状态机，而是每步用 `(绝对时刻 + offset) mod 周期` 直接算出当前相位，
从而保证相位差在整个仿真期间稳定保持（这是绿波协调的前提）。
"""

from __future__ import annotations

from config import SimConfig
from controllers.base import PhaseState, SignalController


class CoordinatedController(SignalController):
    """绿波协调控制器：固定周期 + 相位差。

    相位时钟：clk = (absolute_time + offset) mod cycle。
    cycle 由「两相位绿灯 + 黄灯 + 全红」组成，每个相位绿灯时长由
    half_green 决定（对称配时，绿信比 50/50，可扩展为不均匀）。
    """

    name = "coordinated"
    label = "绿波协调"

    def __init__(self, cfg: SimConfig, offset: float = 0.0, cycle: float = 60.0) -> None:
        self.offset = offset
        self.cycle = cycle
        self.cfg = cfg
        self.g = cfg.fixed_green                          # 各相位绿灯
        self.y = cfg.yellow_seconds
        self.ar = cfg.all_red_seconds
        self.half_period = self.g + self.y + self.ar      # 半周期
        self.full = 2 * self.half_period
        self.name = "coordinated"
        self.label = "绿波协调"
        self.min_green = self.g
        self.max_green = self.g
        self.green_planned = self.g
        self.phase = 0
        self.state = PhaseState.GREEN
        self.green_elapsed = 0.0
        self.state_timer = 0.0
        self.stats = {"green_total": 0.0, "phase_executions": 0, "extensions": 0,
                      "shortened": 0, "per_phase_green": {0: [], 1: []}, "cycle_lengths": []}
        self._sync(0.0)

    def _clock(self, absolute_time: float) -> float:
        """换算到本路口相位时钟（0 ~ full）。"""
        return (absolute_time + self.offset) % self.full

    def _sync(self, absolute_time: float) -> None:
        """根据绝对时间同步相位状态。"""
        clk = self._clock(absolute_time)
        g, y, ar, hp = self.g, self.y, self.ar, self.half_period
        if clk < g:
            self.phase, self.state = 0, PhaseState.GREEN
            self.green_elapsed, self.state_timer = clk, clk
        elif clk < g + y:
            self.phase, self.state = 0, PhaseState.YELLOW
            self.green_elapsed, self.state_timer = g, clk - g
        elif clk < hp:
            self.phase, self.state = 0, PhaseState.ALL_RED
            self.green_elapsed, self.state_timer = g, clk - g - y
        elif clk < hp + g:
            self.phase, self.state = 1, PhaseState.GREEN
            self.green_elapsed, self.state_timer = clk - hp, clk - hp
        elif clk < hp + g + y:
            self.phase, self.state = 1, PhaseState.YELLOW
            self.green_elapsed, self.state_timer = g, clk - hp - g
        else:
            self.phase, self.state = 1, PhaseState.ALL_RED
            self.green_elapsed, self.state_timer = g, clk - hp - g - y

    def update(self, dt: float, snap) -> None:
        """按绝对时间同步相位（时间推进到 now 的量化结果）。"""
        self._sync(snap.now)

    def desired_green(self, phase, snap):
        return self.g

    def initial_green(self, phase, snap):
        return self.g

    @property
    def phase_name(self) -> str:
        from config import PHASE_NAMES

        return PHASE_NAMES[self.phase]

    def info(self) -> dict:
        return {
            "name": self.name, "label": self.label,
            "phase": self.phase, "phase_name": self.phase_name,
            "state": self.state, "green_elapsed": self.green_elapsed,
            "green_planned": self.green_planned, "state_timer": self.state_timer,
            "offset": self.offset, "cycle": self.cycle,
        }


def make_coordinated(cfg: SimConfig, offset: float, cycle: float) -> CoordinatedController:
    return CoordinatedController(cfg, offset=offset, cycle=cycle)
