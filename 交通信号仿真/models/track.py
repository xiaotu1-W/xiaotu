"""路口拓扑与行驶轨迹（纯标量计算，不依赖 pygame）。

坐标系：x 向右、z 向下（屏幕坐标），单位米，路口中心为原点。

方向编号：
    0 = 北进口：车辆从北侧驶入，向南(+z)行驶
    1 = 东进口：车辆从东侧(+x)驶入，向西(-x)行驶
    2 = 南进口：车辆从南侧驶入，向北(-z)行驶
    3 = 西进口：车辆从西侧(-x)驶入，向东(+x)行驶

每个进口道设置三条车道：内侧车道左转、中间车道直行、外侧车道右转，
对应城市道路展宽渠化的常见做法。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from config import SimConfig

DIR_VECTORS = {0: (0.0, 1.0), 1: (-1.0, 0.0), 2: (0.0, -1.0), 3: (1.0, 0.0)}


# --------------------------------------------------------------------------
# 向量小工具
# --------------------------------------------------------------------------
def left_of(vec: tuple[float, float]) -> tuple[float, float]:
    """向量的左侧（屏幕坐标，驾驶员视角左）。"""
    x, z = vec
    return (z, -x)


def right_of(vec: tuple[float, float]) -> tuple[float, float]:
    x, z = vec
    return (-z, x)


def heading_degrees(vec: tuple[float, float]) -> float:
    """向量的屏幕角度（度），用于旋转车体矩形。"""
    return math.degrees(math.atan2(vec[1], vec[0]))


# --------------------------------------------------------------------------
# 轨迹
# --------------------------------------------------------------------------
@dataclass
class Path:
    """一条按里程参数化的行驶轨迹。"""

    direction: int
    move: str                                   # left / through / right
    points: list[tuple[float, float]]           # 折线（左转/右转为贝塞尔采样）
    s_stop: float                               # 停车线对应的里程
    speed_factor: float = 1.0                   # 转弯限速系数
    _cum: list[float] | None = None             # 各顶点累计长度缓存
    _length: float = 0.0

    def __post_init__(self) -> None:
        self._cum = [0.0]
        for i in range(len(self.points) - 1):
            self._cum.append(self._cum[-1] + math.dist(self.points[i], self.points[i + 1]))
        self._length = self._cum[-1]

    @property
    def length(self) -> float:
        return self._length

    def _segment(self, s: float) -> int:
        """定位里程 s 所在线段下标。"""
        assert self._cum is not None
        s = max(0.0, min(s, self._length))
        lo, hi = 0, len(self._cum) - 1
        while lo + 1 < hi:
            mid = (lo + hi) // 2
            if self._cum[mid] <= s:
                lo = mid
            else:
                hi = mid
        return lo

    def position(self, s: float) -> tuple[float, float]:
        i = self._segment(s)
        assert self._cum is not None
        (x0, z0), (x1, z1) = self.points[i], self.points[i + 1]
        seg = self._cum[i + 1] - self._cum[i]
        t = 0.0 if seg <= 1e-9 else (max(0.0, min(s, self._length)) - self._cum[i]) / seg
        return (x0 + (x1 - x0) * t, z0 + (z1 - z0) * t)

    def heading(self, s: float) -> tuple[float, float]:
        i = self._segment(s)
        (x0, z0), (x1, z1) = self.points[i], self.points[i + 1]
        seg = math.hypot(x1 - x0, z1 - z0) or 1.0
        return ((x1 - x0) / seg, (z1 - z0) / seg)


# --------------------------------------------------------------------------
# 车道
# --------------------------------------------------------------------------
@dataclass
class Lane:
    """进口道的一条车道，对应唯一转向。"""

    direction: int
    move: str
    share: float                                # 该转向到达比例
    lane_index: int                             # 0=最内侧
    offset: float                               # 相对道路中线的横向偏移（米，左负右正）
    capacity: float                             # 可容纳车辆数（排队溢出判定）
    path: Path

    @property
    def key(self) -> tuple[int, str]:
        return (self.direction, self.move)


@dataclass
class Topology:
    lanes: list[Lane]
    cfg: SimConfig

    def path_of(self, direction: int, move: str) -> Path:
        for ln in self.lanes:
            if ln.key == (direction, move):
                return ln.path
        raise KeyError((direction, move))

    def lanes_of_phase(self, phase: int) -> list[Lane]:
        from config import approach_phase

        return [ln for ln in self.lanes if approach_phase(ln.direction) == phase]


# --------------------------------------------------------------------------
# 构网
# --------------------------------------------------------------------------
def build_network(cfg: SimConfig) -> Topology:
    lanes: list[Lane] = []
    shares = {"left": cfg.left_ratio, "through": cfg.through_ratio, "right": cfg.right_ratio}
    # 三车道横向偏移：内侧左转在道路中线一侧
    offsets = {"left": -cfg.road_half_width / 2, "through": 0.0, "right": cfg.road_half_width / 2}

    for d in range(4):
        for idx, move in enumerate(("left", "through", "right")):
            if shares[move] <= 0:
                continue
            path = _build_path(cfg, d, move, offsets[move])
            lanes.append(
                Lane(
                    direction=d,
                    move=move,
                    share=shares[move],
                    lane_index=idx,
                    offset=offsets[move],
                    capacity=cfg.storage_capacity,
                    path=path,
                )
            )
    return Topology(lanes=lanes, cfg=cfg)


def _build_path(cfg: SimConfig, d: int, move: str, lane_off: float) -> Path:
    w = cfg.stop_line_offset
    fwd = DIR_VECTORS[d]
    left = left_of(fwd)
    start = (-fwd[0] * cfg.road_length + left[0] * lane_off,
             -fwd[1] * cfg.road_length + left[1] * lane_off)
    stop = (-fwd[0] * w + left[0] * lane_off,
            -fwd[1] * w + left[1] * lane_off)
    s_stop = math.dist(start, stop)

    if move == "through":
        end = (fwd[0] * cfg.road_length + left[0] * lane_off,
               fwd[1] * cfg.road_length + left[1] * lane_off)
        return Path(d, move, [start, stop, end], s_stop, 1.0)

    # 出口车道偏移：左转进入对向出口的内侧车道，右转进入右侧出口的外侧车道
    out = left_of(fwd) if move == "left" else right_of(fwd)
    exit_off = cfg.road_half_width / 2 if move == "left" else -cfg.road_half_width / 2
    end = (out[0] * cfg.road_length + fwd[0] * exit_off,
           out[1] * cfg.road_length + fwd[1] * exit_off)
    # 二次贝塞尔控制点：位于转角方块内部，使转弯轨迹平滑且不越界
    ctrl_scale = 1.15
    ctrl = (-fwd[0] * w * ctrl_scale + out[0] * w * ctrl_scale + fwd[0] * exit_off,
            -fwd[1] * w * ctrl_scale + out[1] * w * ctrl_scale + fwd[1] * exit_off)
    pts = _quad_bezier(stop, ctrl, end, n=10)
    return Path(d, move, [start, stop, *pts[1:]], s_stop, cfg.turn_speed_factor)


def _quad_bezier(p0, ctrl, p2, n: int) -> list[tuple[float, float]]:
    pts = []
    for i in range(n + 1):
        t = i / n
        mt = 1 - t
        pts.append((
            mt * mt * p0[0] + 2 * mt * t * ctrl[0] + t * t * p2[0],
            mt * mt * p0[1] + 2 * mt * t * ctrl[1] + t * t * p2[1],
        ))
    return pts
