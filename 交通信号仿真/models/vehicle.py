"""车辆模型：沿轨迹一维行驶，采用 IDM 跟驰模型 + 信号灯停车约束。

相比原方案「红灯停、绿灯走」的二值逻辑，这里引入了：
* IDM（Intelligent Driver Model）连续跟驰：加减速平滑、不会穿模；
* 安全车头间距：根据前车速度实时估算，避免追尾与重叠；
* 排队判定：速度低于阈值且前方有车/红灯即视为排队；
* 元数据采集：生成/驶离时刻、排队等待时长，供指标模块使用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from config import SimConfig
from models.track import Lane

# 车辆最高限速：50 km/h
FREE_FLOW_SPEED = 13.9


@dataclass
class Vehicle:
    vid: int
    lane: Lane
    s: float = 0.0
    speed: float = 0.0
    accel: float = 0.0
    spawn_time: float = 0.0
    exit_time: float | None = None
    queued: bool = False                 # 本步是否计入排队
    stopped: bool = False                # 本步是否处于完全停止
    wait_start: float | None = None      # 当前等停开始时刻
    total_wait: float = 0.0              # 排队等待累计时长
    _dwell: float = 0.0                  # 连续低速累计时间

    # ------------------------------------------------------------------
    # 几何
    # ------------------------------------------------------------------
    @property
    def path(self):
        return self.lane.path

    @property
    def passed_stop_line(self) -> bool:
        return self.s >= self.path.s_stop

    @property
    def position(self) -> tuple[float, float]:
        return self.path.position(self.s)

    @property
    def heading(self) -> tuple[float, float]:
        return self.path.heading(self.s)

    @property
    def finished(self) -> bool:
        return self.s >= self.path.length

    # ------------------------------------------------------------------
    # 单车限速
    # ------------------------------------------------------------------
    def desired_speed(self) -> float:
        """期望车速：直行取自由流车速，转弯按系数折减并在弯道末端线性恢复。"""
        factor = self.path.speed_factor
        if factor >= 1.0:
            return FREE_FLOW_SPEED
        dist_to_end = self.path.length - self.s
        if not self.passed_stop_line or dist_to_end >= 20.0:
            return FREE_FLOW_SPEED
        blend = 1.0 - dist_to_end / 20.0       # 0 -> 1
        return FREE_FLOW_SPEED * (factor + (1.0 - factor) * blend)

    # ------------------------------------------------------------------
    # IDM 跟驰
    # ------------------------------------------------------------------
    @staticmethod
    def desired_gap(cfg: SimConfig, v: float, leader_speed: float) -> float:
        """IDM 期望车头间距 s*。"""
        dv = v - leader_speed
        return cfg.safety_gap + v * 0.9 + v * dv / (2.0 * math.sqrt(cfg.max_accel * cfg.comfort_decel))

    @staticmethod
    def idm_accel(cfg: SimConfig, v: float, v0: float, gap: float | None, leader_speed: float) -> float:
        """IDM 加速度；gap=None 表示前方没有车。"""
        free = 1.0 - (v / max(v0, 0.1)) ** 4
        if gap is None:
            return cfg.max_accel * free
        s_star = Vehicle.desired_gap(cfg, v, leader_speed)
        return cfg.max_accel * (free - (s_star / max(gap, 0.3)) ** 2)

    @staticmethod
    def stop_distance(speed: float, decel: float) -> float:
        """以给定减速度刹停所需距离。"""
        return speed * speed / (2.0 * max(decel, 0.1))

    # ------------------------------------------------------------------
    # 状态推进
    # ------------------------------------------------------------------
    def integrate(self, dt: float) -> None:
        self.speed = max(0.0, self.speed + self.accel * dt)
        self.s = min(self.path.length, self.s + self.speed * dt)

    def update_queue_state(self, dt: float, now: float, held: bool) -> None:
        """更新排队 / 等待统计。

        held=True 表示本步被前车或红灯挡住。
        连续低速 0.5 秒以上计为排队，滤掉瞬时减速带来的噪声。
        """
        if held and self.speed < 0.8:
            self._dwell += dt
        else:
            self._dwell = max(0.0, self._dwell - dt)

        was_queued = self.queued
        self.queued = self._dwell >= 0.5
        self.stopped = held and self.speed < 0.1

        if self.queued and not was_queued:
            self.wait_start = now
        elif was_queued and not self.queued:
            self.close_wait(now)

    def close_wait(self, now: float) -> None:
        if self.wait_start is not None:
            self.total_wait += max(0.0, now - self.wait_start)
            self.wait_start = None
        self.queued = False
