"""多路口网格路网模型。

设计目标：把单个十字路口扩成 rows × cols 的矩形网格，相邻路口之间用
「路段」（link）连接，车辆跨越一个路口后进入下一个路段继续行驶。

坐标系约定（与单路口一致）：x 向右、z 向下（屏幕坐标），单位米。

路口编号：intersection (i, j)，i 为行（z 方向），j 为列（x 方向）。
    (0,0) 左上角，(rows-1, cols-1) 右下角。

每个路口仍是四方向（北/东/南/西）进口道；网格内的相邻路口共享一条路段，
车辆从 A 路口的某出口驶出即进入 B 路口的对应进口，形成「联动」。

绿波协调：所有路口共享同一公共周期，按相邻路口东西方向的距离与期望车速
计算「相位差 offset」，使沿主干道（东西向）行驶的车流能在绿灯窗口连续通过。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from config import SimConfig, approach_phase
from models.track import Lane, Path, build_network, DIR_VECTORS, left_of, right_of


@dataclass
class Link:
    """相邻两路口之间的路段。

    a, b: 两端的路口坐标 (i, j)；
    direction_from_a: 从 a 视角出发的方向编号（车辆沿此方向离开 a 进入 b）；
    路段长度默认取 link_length（米）。
    """

    a: tuple[int, int]
    b: tuple[int, int]
    length: float
    direction_from_a: int


@dataclass
class GridNetwork:
    """矩形网格路网。"""

    rows: int
    cols: int
    link_length: float          # 相邻路口中心距离（米）
    cfg: SimConfig
    intersections: list = field(default_factory=list)   # [(i,j), ...]
    links: list[Link] = field(default_factory=list)

    def __post_init__(self) -> None:
        for i in range(self.rows):
            for j in range(self.cols):
                self.intersections.append((i, j))
        # 横向路段（东西向）：同行的相邻列
        for i in range(self.rows):
            for j in range(self.cols - 1):
                self.links.append(Link((i, j), (i, j + 1), self.link_length, 1))   # 方向 1 = 东
                self.links.append(Link((i, j + 1), (i, j), self.link_length, 3))   # 方向 3 = 西
        # 纵向路段（南北向）：同列的相邻行
        for i in range(self.rows - 1):
            for j in range(self.cols):
                self.links.append(Link((i, j), (i + 1, j), self.link_length, 2))   # 方向 2 = 南
                self.links.append(Link((i + 1, j), (i, j), self.link_length, 0))   # 方向 0 = 北

    def idx_of(self, i: int, j: int) -> int:
        return i * self.cols + j

    def coord_of(self, idx: int) -> tuple[int, int]:
        return (idx // self.cols, idx % self.cols)

    def neighbors(self, i: int, j: int) -> list[tuple[int, int]]:
        """四邻接路口。"""
        out = []
        for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            ni, nj = i + di, j + dj
            if 0 <= ni < self.rows and 0 <= nj < self.cols:
                out.append((ni, nj))
        return out

    def link_between(self, a: tuple[int, int], b: tuple[int, int], direction_from_a: int) -> Link | None:
        for ln in self.links:
            if ln.a == a and ln.b == b and ln.direction_from_a == direction_from_a:
                return ln
        return None


def build_grid(rows: int, cols: int, link_length: float, cfg: SimConfig) -> GridNetwork:
    """构造网格路网。"""
    return GridNetwork(rows=rows, cols=cols, link_length=link_length, cfg=cfg)


def green_wave_offset(link_length: float, speed_mps: float) -> float:
    """绿波相位差：车辆以 speed_mps 行驶 link_length 所需时间（秒）。

    下游路口绿灯相对上游「延后」这个时间，使刚通过上游路口的车能赶上
    下游绿灯窗口。单位：秒。
    """
    if speed_mps <= 0:
        return 0.0
    return link_length / speed_mps


def wave_speed_from_distance(link_length: float, target_offset: float) -> float:
    """给定期望相位差，反推绿波车速（调试用）。"""
    return link_length / max(target_offset, 1e-6)
