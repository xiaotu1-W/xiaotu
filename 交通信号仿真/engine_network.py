"""多路口网格微观仿真引擎。

模型
----
* rows × cols 的矩形网格，每个网格点是一个十字路口；
* 路口之间由「路段」连接：车辆从路口 A 的某出口驶出，沿路段行驶到
  路口 B 的对应进口道，然后按转向（左/直/右）进入 B 的另一条出口路段；
* 网格外围边界作为「车流入口」：车辆从这里进入路网，穿过若干路口后
  从对侧边界驶离。

协调
----
* coordinated=False：每个路口独立运行自己的信号策略（固定/自适应/Webster）；
* coordinated=True：所有路口共享周期，按东西向绿波相位差协调。

每「步」的推进顺序：更新信号机 -> 更新各路段车辆（IDM 跟驰 + 红灯停车）
-> 车辆跨路口转移 -> 生成边界车流 -> 采集指标。
"""

from __future__ import annotations

import math
import random

from config import SimConfig, approach_phase
from controllers.base import PhaseSnapshot, PhaseState, SignalController
from controllers.strategies import create_controller
from controllers.coordinated import make_coordinated
from models.track import Lane, build_network
from models.vehicle import Vehicle
from models.network import GridNetwork, build_grid, green_wave_offset

# 方向编号：0=北进口(向南行驶) 1=东进口(向西行驶) 2=南进口(向北行驶) 3=西进口(向东行驶)
# 与单路口 config.approach_phase 一致。
# 旅行方向（车辆前进的网格位移）：
APPROACH_TRAVEL = {0: (1, 0), 1: (0, -1), 2: (-1, 0), 3: (0, 1)}   # 行/列位移
DIR_NAME = {0: "北", 1: "东", 2: "南", 3: "西"}


class NetVehicle:
    """路段上行驶的车辆。"""

    __slots__ = ("vid", "from_i", "from_j", "dir", "s", "speed", "accel",
                 "turn", "spawn_time", "exit_time", "total_wait", "wait_start",
                 "queued", "stopped", "_dwell", "_last_s")

    def __init__(self, vid, from_i, from_j, direction, turn, spawn_time):
        self.vid = vid
        self.from_i = from_i            # 所在路段起点路口（行）
        self.from_j = from_j            # 所在路段起点路口（列）
        self.dir = direction            # 行驶方向
        self.s = 0.0                    # 距路段起点的里程
        self.speed = 0.0
        self.accel = 0.0
        self.turn = turn                # 到下一路口的转向 left/through/right
        self.spawn_time = spawn_time
        self.exit_time = None
        self.total_wait = 0.0
        self.wait_start = None
        self.queued = False
        self.stopped = False
        self._dwell = 0.0
        self._last_s = 0.0

    @property
    def link_key(self):
        return (self.from_i, self.from_j, self.dir)


class NetworkSimulation:
    """多路口网格仿真器。

    direction_bias: 方向需求偏向。None 表示四个进口等量；
    设为某方向编号（如 3=西进口，即东西向主干道）时，该方向入口需求放大，
    用于模拟「早高峰单向潮汐主干道」——绿波协调的主战场。
    """

    def __init__(
        self,
        cfg: SimConfig | None = None,
        rows: int = 2,
        cols: int = 2,
        link_length: float = 200.0,
        strategy: str = "fixed",
        coordinated: bool = False,
        wave_speed: float = 13.9,
        direction_bias: int | None = None,
        bias_factor: float = 1.0,
    ) -> None:
        self.cfg = cfg or SimConfig()
        self.rows = rows
        self.cols = cols
        self.link_length = link_length
        self.strategy = strategy
        self.coordinated = coordinated
        self.wave_speed = wave_speed
        self.direction_bias = direction_bias
        self.bias_factor = bias_factor
        self.grid = build_grid(rows, cols, link_length, self.cfg)
        self.rng = random.Random(self.cfg.seed)

        # 每路口一个控制器
        self.controllers: dict[tuple[int, int], SignalController] = {}
        self._init_controllers()

        # 车辆（路段上）
        self.vehicles: list[NetVehicle] = []
        self._next_vid = 0

        # 统计
        self.t = 0.0
        self.measuring = False
        self.measure_start = self.cfg.warmup_seconds
        self.measure_end = self.cfg.total_seconds
        self.departed = 0
        self.spawned_measured = 0
        self.total_spawned = 0
        self.max_total_queue = 0
        self._depart_times: list[float] = []
        self._arrivals_trace: list[tuple[float, int]] = []
        self._last_cross: dict[int, float] = {}
        self.series: dict[str, list] = {
            "t": [], "total_queue": [], "throughput": [], "mean_wait": [], "vehicles": [],
        }
        self._series_timer = 0.0
        self._wait_samples: list[float] = []
        self._green_ns: list[float] = []
        self._green_ew: list[float] = []

        # 边界入口：每个边界方向维护到达时刻（泊松）
        self._entry_next: dict[tuple[int, int, int], float] = {}
        self._init_entries()

    # ==================================================================
    # 初始化
    # ==================================================================
    def _init_controllers(self) -> None:
        cycle = self.cfg.cycle_seconds
        offset_per_link = green_wave_offset(self.link_length, self.wave_speed)
        for i in range(self.rows):
            for j in range(self.cols):
                if self.coordinated:
                    offset = j * offset_per_link       # 东西向绿波：东移则延后
                    self.controllers[(i, j)] = make_coordinated(self.cfg, offset, cycle)
                else:
                    self.controllers[(i, j)] = create_controller(self.strategy, self.cfg)

    def _init_entries(self) -> None:
        """登记边界车流入口。

        车辆沿方向 d 行驶，其「进入路网的第一个路口」是 (i,j)，而它来自
        上游一格 (i-di, j-dj)。当上游格落在网格之外时，(i,j) 就是边界进口。
        这样车流能真正横穿整个网格，而不是只经过一个路口就驶离。
        """
        for i in range(self.rows):
            for j in range(self.cols):
                for d in range(4):
                    di, dj = APPROACH_TRAVEL[d]
                    ui, uj = i - di, j - dj
                    if not (0 <= ui < self.rows and 0 <= uj < self.cols):
                        self._entry_next[(i, j, d)] = self._sample_headway(d)

    # ==================================================================
    # 车流生成
    # ==================================================================
    def _sample_headway(self, direction: int) -> float:
        rate = self.cfg.demand_at(self.t, direction) / 3600.0
        if self.direction_bias is not None and direction == self.direction_bias:
            rate *= self.bias_factor
        if rate <= 0:
            return float("inf")
        return self.rng.expovariate(rate)

    def _spawn_entry(self, i: int, j: int, d: int) -> None:
        """从边界进口 d 向路口 (i,j) 生成一辆车。

        车辆「从边界外」驶来，其所在路段的起点是「虚拟的边界上路格」，
        前方第一个路口就是 (i,j)。用 from_i/from_j 记录这个虚拟起点，
        使 _next_intersection 能正确返回 (i,j)。
        di, dj = APPROACH_TRAVEL[d] 为旅行方向，(i,j) 是车辆进入的第一个路口，
        因此所在路段「起点」应位于 (i - di, j - dj)（边界外一格）。
        """
        di, dj = APPROACH_TRAVEL[d]
        from_i, from_j = i - di, j - dj
        turn = self._sample_turn()
        v = NetVehicle(self._next_vid, from_i, from_j, d, turn, self.t)
        self._next_vid += 1
        self.vehicles.append(v)
        self.total_spawned += 1
        if self.measuring:
            self.spawned_measured += 1
            self._arrivals_trace.append((self.t, approach_phase(d)))

    def _sample_turn(self) -> str:
        r = self.rng.random()
        if r < self.cfg.left_ratio:
            return "left"
        if r < self.cfg.left_ratio + self.cfg.through_ratio:
            return "through"
        return "right"

    # ==================================================================
    # 几何辅助
    # ==================================================================
    def _link_start(self, i: int, j: int, d: int) -> tuple[float, float]:
        """以路口 (i,j) 为起点、方向 d 的路段起点坐标（世界坐标）。"""
        x0 = (j - (self.cols - 1) / 2) * self.link_length
        z0 = (i - (self.rows - 1) / 2) * self.link_length
        return (x0, z0)

    def _vehicle_position(self, v: NetVehicle) -> tuple[float, float]:
        x0, z0 = self._link_start(v.from_i, v.from_j, v.dir)
        # 旅行方向（屏幕坐标：x 右、z 下）
        dv = {0: (0.0, 1.0), 1: (-1.0, 0.0), 2: (0.0, -1.0), 3: (1.0, 0.0)}[v.dir]
        return (x0 + dv[0] * v.s, z0 + dv[1] * v.s)

    def _next_intersection(self, v: NetVehicle) -> tuple[int, int] | None:
        """车辆前方第一个路口（路段终点）。"""
        di, dj = APPROACH_TRAVEL[v.dir]
        ni, nj = v.from_i + di, v.from_j + dj
        if 0 <= ni < self.rows and 0 <= nj < self.cols:
            return (ni, nj)
        return None   # 驶离路网

    def _is_green_for(self, i: int, j: int, direction: int) -> bool:
        """路口 (i,j) 的 direction 方向进口是否有通行权（绿灯）。"""
        c = self.controllers[(i, j)]
        if approach_phase(direction) != c.phase:
            return False
        return c.state == PhaseState.GREEN

    # ==================================================================
    # 排队与通行
    # ==================================================================
    def _stop_line_s(self, v: NetVehicle) -> float:
        """车辆前方停车线里程：距下一路口中心 stop_line_offset。"""
        return self.link_length - self.cfg.stop_line_offset

    def total_queue(self) -> int:
        n = 0
        for v in self.vehicles:
            if v.queued:
                n += 1
        return n

    # ==================================================================
    # 主循环
    # ==================================================================
    def step(self) -> None:
        dt = self.cfg.sim_dt
        if not self.measuring and self.t >= self.measure_start:
            self.measuring = True

        # 1) 统计各路口排队（一次遍历，避免每控制器重复扫全量车辆）
        q_by_inter = {key: {0: 0, 1: 0} for key in self.controllers}
        for v in self.vehicles:
            if v.queued:
                nxt = self._next_intersection(v)
                if nxt is not None and nxt in q_by_inter:
                    q_by_inter[nxt][approach_phase(v.dir)] += 1

        # 2) 信号机推进
        arr = self._arrivals_15s()
        last_cross = {0: self._last_cross.get(0, -1e9), 1: self._last_cross.get(1, -1e9)}
        for key, c in self.controllers.items():
            snap = PhaseSnapshot(now=self.t, queues=q_by_inter[key], arrivals_15s=arr,
                                 last_green={0: 0.0, 1: 0.0}, last_cross=last_cross)
            c.update(dt, snap)

        # 3) 边界车流生成
        for (i, j, d) in list(self._entry_next):
            while self.t >= self._entry_next[(i, j, d)]:
                self._spawn_entry(i, j, d)
                self._entry_next[(i, j, d)] += self._sample_headway(d)

        # 4) 车辆更新（按路段分桶，队首在前）
        links: dict[tuple, list[NetVehicle]] = {}
        for v in self.vehicles:
            links.setdefault(v.link_key, []).append(v)
        for key, group in links.items():
            group.sort(key=lambda x: x.s, reverse=True)
            for v in group:
                self._update_vehicle(v, group)

        # 4) 跨路口转移 / 驶离
        self._transfer()

        # 5) 采样
        if self.measuring:
            q = self.total_queue()
            self.max_total_queue = max(self.max_total_queue, q)
            self._series_timer += dt
            if self._series_timer >= 1.0:
                self._series_timer = 0.0
                self._push_series()

        self.t += dt

    # ------------------------------------------------------------------
    def _snapshot(self, i: int, j: int) -> PhaseSnapshot:
        q = self._queue_by_phase(i, j)
        arr = self._arrivals_15s()
        last_cross = {0: self._last_cross.get(0, -1e9), 1: self._last_cross.get(1, -1e9)}
        return PhaseSnapshot(now=self.t, queues=q, arrivals_15s=arr,
                              last_green={0: 0.0, 1: 0.0}, last_cross=last_cross)

    def _queue_by_phase(self, i: int, j: int) -> dict[int, int]:
        out = {0: 0, 1: 0}
        for v in self.vehicles:
            if v.queued and self._next_intersection(v) == (i, j):
                out[approach_phase(v.dir)] += 1
        return out

    def _arrivals_15s(self) -> dict[int, int]:
        cutoff = self.t - 15.0
        out = {0: 0, 1: 0}
        for t, p in self._arrivals_trace:
            if t >= cutoff:
                out[p] += 1
        # 定期裁剪，避免长时间仿真下轨迹无限增长
        if len(self._arrivals_trace) > 2000:
            self._arrivals_trace = [x for x in self._arrivals_trace if x[0] >= cutoff]
        return out

    # ------------------------------------------------------------------
    def _leader(self, v: NetVehicle, group: list[NetVehicle]) -> tuple[NetVehicle | None, float]:
        """同路段前车（s 更大者）与净间距。"""
        best = None
        best_gap = float("inf")
        for o in group:
            if o is v:
                continue
            gap = o.s - v.s - self.cfg.vehicle_length
            if -1e-6 <= gap < best_gap:
                best, best_gap = o, gap
        return best, best_gap

    def _update_vehicle(self, v: NetVehicle, group: list[NetVehicle] | None = None) -> None:
        cfg = self.cfg
        if group is None:
            group = [o for o in self.vehicles if o.link_key == v.link_key]
        leader, gap = self._leader(v, group)
        leader_speed = leader.speed if leader else v.speed
        gap_to_leader = gap if leader else None
        v0 = 13.9

        acc = Vehicle.idm_accel(cfg, v.speed, v0, gap_to_leader, leader_speed)

        # 红灯停车
        held = False
        nxt = self._next_intersection(v)
        stop_s = self._stop_line_s(v)
        barrier = None
        if nxt is not None and not self._is_green_for(nxt[0], nxt[1], v.dir):
            dist = stop_s - v.s
            if dist > 0.3:
                barrier = dist
                held = True
        if barrier is not None:
            brake = Vehicle.idm_accel(cfg, v.speed, v0, barrier, 0.0)
            acc = min(acc, brake)

        acc = max(acc, -2.0 * cfg.comfort_decel)
        v.accel = acc
        v._last_s = v.s
        v.speed = max(0.0, v.speed + acc * cfg.sim_dt)
        v.s = v.s + v.speed * cfg.sim_dt

        if leader is not None and v.s > leader.s - cfg.vehicle_length:
            v.s = leader.s - cfg.vehicle_length
            v.speed = min(v.speed, leader.speed)

        # 排队状态
        if held and v.speed < 0.8:
            v._dwell += cfg.sim_dt
        else:
            v._dwell = max(0.0, v._dwell - cfg.sim_dt)
        was_queued = v.queued
        v.queued = v._dwell >= 0.5
        v.stopped = held and v.speed < 0.1
        if v.queued and not was_queued:
            v.wait_start = self.t
        elif was_queued and not v.queued:
            self._close_wait(v)

    def _close_wait(self, v: NetVehicle) -> None:
        if v.wait_start is not None:
            v.total_wait += max(0.0, self.t - v.wait_start)
            v.wait_start = None
        v.queued = False

    def _transfer(self) -> None:
        """车辆越过路口 / 驶离：转移到下一路段或计为驶离。"""
        remaining = []
        for v in self.vehicles:
            nxt = self._next_intersection(v)
            stop_s = self.cfg.stop_line_offset
            end = self.link_length + stop_s      # 越过路口中心再进入下一路段
            if v.s >= end:
                if nxt is not None:
                    # 进入下一路段：位置回退到「从下一路口中心出发」的起点
                    v.from_i, v.from_j = nxt
                    v.s = v.s - end
                    v.turn = self._sample_turn()   # 新路口的转向
                    v._dwell = 0.0
                    v.queued = False
                    v.speed = max(v.speed, 4.0)    # 保持一定速度穿过路口
                    remaining.append(v)
                else:
                    # 驶离路网
                    v.exit_time = self.t
                    self._close_wait(v)
                    self.departed += 1
                    self._depart_times.append(self.t)
                    if self.measuring:
                        self._wait_samples.append(v.total_wait)
            else:
                remaining.append(v)
        self.vehicles = remaining

    def _push_series(self) -> None:
        self.series["t"].append(round(self.t, 1))
        self.series["total_queue"].append(self.total_queue())
        self.series["vehicles"].append(len(self.vehicles))
        self.series["throughput"].append(round(self.throughput_window(), 1))
        waits = self._wait_samples
        self.series["mean_wait"].append(round(sum(waits) / len(waits), 2) if waits else 0.0)

    def throughput_window(self, seconds: float = 60.0) -> float:
        if not self.measuring:
            return 0.0
        cutoff = self.t - seconds
        recent = sum(1 for x in self._depart_times if x >= cutoff)
        return recent * 3600.0 / seconds

    # ==================================================================
    # 运行与结果
    # ==================================================================
    def run(self) -> dict:
        while self.t < self.cfg.total_seconds:
            self.step()
        return self.result()

    def capture_state(self, t: float) -> dict:
        """给定时刻，捕获车辆与信号状态（供 HTML 动画 + Web 使用）。

        车辆返回 (i, j, s, dir, turn, queued)；信号返回每个路口的灯色。
        """
        # 推进到时刻 t（若 t 小于当前则忽略）
        while self.t < t:
            self.step()
        vehicles = []
        for v in self.vehicles:
            nxt = self._next_intersection(v)
            vehicles.append({
                "i": v.from_i, "j": v.from_j, "s": round(v.s, 1), "dir": v.dir,
                "turn": v.turn, "queued": v.queued,
            })
        signals = {}
        for (i, j), c in self.controllers.items():
            signals[f"{i},{j}"] = c.state
        return {"vehicles": vehicles, "signals": signals, "t": round(self.t, 1),
                "queue": self.total_queue()}

    def result(self) -> dict:
        waits = self._wait_samples
        window = self.cfg.measure_seconds
        throughput = self.departed * 3600.0 / window if window > 0 else 0.0
        n = len(waits)
        green_ns = self._green_ns
        green_ew = self._green_ew
        return {
            "strategy": "coordinated" if self.coordinated else self.strategy,
            "coordinated": self.coordinated,
            "rows": self.rows,
            "cols": self.cols,
            "departed": self.departed,
            "throughput_vph": round(throughput, 1),
            "mean_wait": round(sum(waits) / n, 2) if n else 0.0,
            "max_wait": round(max(waits), 2) if waits else 0.0,
            "max_queue": int(self.max_total_queue),
            "series": self.series,
            "vehicles": len(self.vehicles),
            "link_length": self.link_length,
        }

    def to_dict(self) -> dict:
        return self.result()
