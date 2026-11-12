"""全局配置：所有可调参数集中在这里，避免散落在各处。

设计原则
--------
* 物理量统一使用「米 / 秒」，与信号配时工程惯例一致；
* 仿真步长固定为 SIM_DT 秒，主循环用累加器把真实帧率与仿真步长解耦，
  这样无论电脑快慢、渲染帧率高低，仿真结果都一致（可复现）；
* 方向、进口道编号等结构常数集中定义，方便以后扩展。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields

# --------------------------------------------------------------------------
# 基本方向定义
# --------------------------------------------------------------------------
# 方向编号：0=北进口(车辆从北向南驶入) 1=东进口 2=南进口 3=西进口
# 0、2 构成南北相位(N-S)，1、3 构成东西相位(E-W)
DIRECTIONS = (0, 1, 2, 3)
DIR_NAMES = ("北进口", "东进口", "南进口", "西进口")
MOVES = ("left", "through", "right")
MOVE_NAMES = {"left": "左转", "through": "直行", "right": "右转"}
PHASE_NAMES = ("南北直行/右转", "东西直行/右转")


def approach_phase(direction: int) -> int:
    """进口道 -> 所属相位编号（0=南北，1=东西）。"""
    return 0 if direction % 2 == 0 else 1


# --------------------------------------------------------------------------
# 仿真参数
# --------------------------------------------------------------------------
@dataclass
class SimConfig:
    # ---- 场景几何（单位：米）----
    road_half_width: float = 10.5       # 单侧半幅路宽（三车道 3.5m*3）
    road_length: float = 160.0          # 每条道路从路口中心到边界的长度
    stop_line_offset: float = 12.0      # 停车线距路口中心的距离
    vehicle_length: float = 4.6
    safety_gap: float = 2.0             # 停车时车头至前车车尾的最小间距
    max_accel: float = 2.5              # 舒适加速度 m/s^2
    comfort_decel: float = 4.0          # 舒适减速度 m/s^2
    turn_speed_factor: float = 0.6      # 转弯限速系数
    saturation_headway: float = 2.0     # 饱和车头时距（秒），判断是否过饱和
    storage_capacity: float = 40.0      # 单个进口道可容纳车辆数（排队溢出判定）

    # ---- 车流 ----
    demand_vph: float = 600.0           # 每个进口道基准到达率（辆/小时）
    demand_ratio_ew: float = 1.0        # 东西向需求 / 南北向需求（模拟主次干道不均衡）
    # 时变需求：((起始秒, 南北到达率, 东西/南北比), ...)，按起始秒升序；
    # 为空表示恒定需求。用于模拟「潮汐车流」——自适应配时的主战场。
    demand_profile: tuple = ()
    left_ratio: float = 0.2             # 转向比例：左转 / 直行 / 右转
    through_ratio: float = 0.6
    # right = 1 - left - through

    # ---- 信号配时 ----
    cycle_seconds: float = 60.0         # 公共周期
    yellow_seconds: float = 3.0
    all_red_seconds: float = 2.0
    min_green: float = 8.0              # 自适应策略的最小 / 最大绿灯
    max_green: float = 32.0
    fixed_green: float = 25.0           # 固定配时各相位绿灯
    max_wait_cap: float = 120.0         # 自适应策略：等待超过该值的相位强制放行

    # ---- 仿真控制 ----
    sim_dt: float = 1.0 / 30.0          # 仿真步长（秒）
    warmup_seconds: float = 300.0       # 预热期：只跑不统计
    measure_seconds: float = 1800.0     # 统计期长度
    seed: int = 7

    def __post_init__(self) -> None:
        non_negative = ("road_half_width", "road_length", "stop_line_offset", "vehicle_length",
                        "safety_gap", "max_accel", "comfort_decel", "demand_vph",
                        "cycle_seconds", "yellow_seconds", "all_red_seconds", "min_green",
                        "max_green", "fixed_green", "max_wait_cap", "warmup_seconds",
                        "measure_seconds", "storage_capacity", "saturation_headway")
        for name in non_negative:
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"{name} 不能为负数")
        if self.road_half_width <= 0 or self.road_length <= 0:
            raise ValueError("道路尺寸必须为正数")
        if not 0 < self.stop_line_offset < self.road_length:
            raise ValueError("stop_line_offset 必须位于道路范围内")
        if self.saturation_headway <= 0:
            raise ValueError("saturation_headway 必须为正数")
        if self.demand_ratio_ew < 0:
            raise ValueError("demand_ratio_ew 不能为负数")
        if self.cycle_seconds <= 0 or self.yellow_seconds + self.all_red_seconds >= self.cycle_seconds:
            raise ValueError("信号周期必须为正，且黄灯与全红时间之和小于周期")
        if self.left_ratio < 0 or self.through_ratio < 0:
            raise ValueError("转向比例不能为负数")
        if self.min_green <= 0 or self.max_green <= 0 or self.fixed_green <= 0:
            raise ValueError("绿灯时间必须为正数")
        if not (0.0 <= self.left_ratio + self.through_ratio <= 1.0):
            raise ValueError("左转 + 直行比例不能超过 1")
        if self.min_green > self.max_green:
            raise ValueError("min_green 不能大于 max_green")
        if self.demand_vph < 0:
            raise ValueError("车流量不能为负数")
        if self.sim_dt <= 0:
            raise ValueError("sim_dt 必须为正")
        if self.demand_profile:
            starts = [s for s, _, _ in self.demand_profile]
            if starts != sorted(starts):
                raise ValueError("demand_profile 必须按起始时间升序")
            if any(s < 0 or n < 0 or r < 0 for s, n, r in self.demand_profile):
                raise ValueError("需求曲线的时间和流量参数不能为负数")

    # ------------------------------------------------------------
    # 便捷换算
    # ------------------------------------------------------------
    @property
    def total_seconds(self) -> float:
        return self.warmup_seconds + self.measure_seconds

    @property
    def right_ratio(self) -> float:
        return max(0.0, 1.0 - self.left_ratio - self.through_ratio)

    def direction_demand(self, direction: int) -> float:
        """某进口道的到达率（辆/小时），东西向按 demand_ratio_ew 缩放。"""
        base = self.demand_vph
        if direction in (1, 3):                     # 东、西进口
            base *= self.demand_ratio_ew
        return base

    def demand_at(self, t: float, direction: int) -> float:
        """某进口道在时刻 t 的到达率（辆/小时），支持时变需求。"""
        if not self.demand_profile:
            return self.direction_demand(direction)
        ns, ratio = self.demand_vph, self.demand_ratio_ew
        for start, n, r in self.demand_profile:
            if t >= start:
                ns, ratio = n, r
            else:
                break
        base = ns if direction in (0, 2) else ns * ratio
        return base

    @property
    def max_direction_demand(self) -> float:
        """最繁忙进口道的到达率（用于饱和度计算）。"""
        return self.demand_vph * max(1.0, self.demand_ratio_ew)

    @property
    def capacity_vph(self) -> float:
        """单个进口道理论饱和通行能力（辆/小时）。"""
        return 3600.0 / self.saturation_headway

    @property
    def saturation_ratio(self) -> float:
        """v/c 比：最繁忙进口道到达率 / 饱和流率，用于判断是否接近过饱和。"""
        return self.max_direction_demand / self.capacity_vph

    def total_demand_vph(self) -> float:
        """四个进口道合计到达率（辆/小时）。"""
        return self.demand_vph * 2 * (1.0 + self.demand_ratio_ew)

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "SimConfig":
        allowed = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in allowed})

    @classmethod
    def from_vph(cls, vph: float, **overrides) -> "SimConfig":
        """用单个进口道到达率构造配置（批量实验常用）。"""
        return cls(demand_vph=vph, **overrides)


# --------------------------------------------------------------------------
# 界面 / 配色
# --------------------------------------------------------------------------
THEME = {
    "bg": (9, 14, 26),              # 深藏青背景
    "panel": (16, 24, 40),
    "panel_border": (38, 52, 76),
    "asphalt": (33, 39, 51),
    "asphalt_edge": (52, 60, 74),
    "lane_mark": (214, 219, 228),
    "stop_line": (235, 238, 244),
    "text": (226, 232, 240),
    "text_dim": (140, 152, 172),
    "accent": (45, 212, 191),       # 青绿色
    "car_through": (45, 212, 191),
    "car_left": (129, 140, 248),
    "car_right": (250, 204, 21),
    "car_queued": (244, 114, 182),
    "red": (239, 68, 68),
    "yellow": (234, 179, 8),
    "green": (34, 197, 94),
    "fixed": (129, 140, 248),
    "actuated": (45, 212, 191),
    "webster": (250, 204, 21),
}

WINDOW_SIZE = (1480, 900)
FPS = 60


# --------------------------------------------------------------------------
# 存储配置
# --------------------------------------------------------------------------
def database_config_from_env() -> dict:
    """从环境变量读取数据库配置。

    设置 MYSQL_HOST 等变量即启用 MySQL；不设置时自动使用项目内的 SQLite，
    保证「没有数据库服务器也能一条命令跑通」。
    """
    mysql_host = os.getenv("MYSQL_HOST")
    if mysql_host:
        return {
            "backend": "mysql",
            "host": mysql_host,
            "port": int(os.getenv("MYSQL_PORT", "3306")),
            "user": os.getenv("MYSQL_USER", "root"),
            "password": os.getenv("MYSQL_PASSWORD", ""),
            "database": os.getenv("MYSQL_DATABASE", "traffic_sim"),
        }
    return {"backend": "sqlite", "path": os.getenv("SQLITE_PATH", "data/traffic_sim.db")}


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def project_path(*parts: str) -> str:
    """返回项目内相对路径（自动相对于本文件所在目录）。"""
    return os.path.join(BASE_DIR, *parts)
