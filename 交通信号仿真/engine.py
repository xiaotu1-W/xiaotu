"""仿真引擎。

职责边界
--------
* 生成车辆（泊松过程到达）；
* 推进信号机（调用控制器）；
* 逐车更新（IDM 跟驰 + 红灯停车约束）；
* 采集排队长度、等待时长、吞吐量等运行数据（仅在统计期采集）。

所有逻辑都是确定性的：给定 SimConfig.seed，同一配置、同一策略的仿真
结果完全一致，这是批量对比与单元测试的前提。
"""

from __future__ import annotations

import bisect
import math
import random
from dataclasses import dataclass, field

from config import SimConfig, approach_phase
from controllers.base import PhaseSnapshot, PhaseState, SignalController
from controllers.strategies import create_controller
from models.track import Lane, Topology, build_network
from models.vehicle import Vehicle


@dataclass
class LiveSnapshot:
    """给 UI / 图表用的实时快照。"""

    t: float
    phase: int
    state: str
    green_elapsed: float
    queue_by_phase: dict[int, int]
    queue_by_lane: dict[tuple[int, str], int]
    vehicles: int
    throughput_vph: float


@dataclass
class SimResult:
    strategy: str
    config: dict
    metrics: dict = field(default_factory=dict)
    time_series: dict = field(default_factory=dict)
    controller_stats: dict = field(default_factory=dict)
    per_lane: dict = field(default_factory=dict)
    per_phase: dict = field(default_factory=dict)

    def __getitem__(self, key: str):
        return self.metrics[key]


class Simulation:
    """离散时间微观交通仿真器。"""

    def __init__(
        self,
        cfg: SimConfig | None = None,
        strategy: str = "actuated",
        topology: Topology | None = None,
        controller: SignalController | None = None,
    ) -> None:
        self.cfg = cfg or SimConfig()
        self.topology = topology or build_network(self.cfg)
        self.controller = controller or create_controller(strategy, self.cfg)
        self.strategy = self.controller.name
        self.rng = random.Random(self.cfg.seed)

        self.t = 0.0
        self.vehicles: list[Vehicle] = []
        # 按车道分桶：车辆从不换道、从不超车，故每桶天然按里程升序，
        # 用它把「找前车」「数排队」从 O(总车辆数) 降到 O(单车道的车辆数)。
        self._lane_lists: dict[tuple[int, str], list[Vehicle]] = {}
        self._next_vid = 0
        self._next_spawn: dict[tuple[int, str], float] = {}

        # 统计区
        self.measuring = False
        self.measure_start = self.cfg.warmup_seconds
        self.measure_end = self.cfg.total_seconds

        # 指标累计
        self.departed: list[dict] = []          # 统计期内驶离车辆
        self.spawned_measured = 0
        self.total_spawned = 0
        self.max_queue = 0
        self.queue_samples: dict[tuple[int, str], list[int]] = {}
        self.series: dict[str, list] = {
            "t": [], "queue_ns": [], "queue_ew": [],
            "throughput": [], "mean_wait": [], "vehicles": [],
        }
        self._series_timer = 0.0
        self._depart_minute: list[int] = []
        self._queue_sum = 0.0
        self._queue_count = 0

        # 每个进口道的累计数据
        self.lane_stats: dict[tuple[int, str], dict] = {
            ln.key: {"departed": 0, "wait_total": 0.0, "wait_samples": 0, "max_queue": 0, "queue_sum": 0.0,
                     "queue_samples": 0, "hours": 0.0}
            for ln in self.topology.lanes
        }
        self.phase_stats: dict[int, dict] = {
            p: {"departed": 0, "wait_total": 0.0, "wait_samples": 0, "green": 0.0, "vehicles": 0}
            for p in (0, 1)
        }
        self._last_green: dict[int, float] = {0: 0.0, 1: 0.0}
        self._arrivals_trace: list[tuple[float, int]] = []
        self._depart_times: list[float] = []
        self._last_cross: dict[int, float] = {0: -1e9, 1: -1e9}

        for ln in self.topology.lanes:
            self._lane_lists[ln.key] = []
            self._next_spawn[ln.key] = self._sample_headway(ln)

    # ==================================================================
    # 车流生成
    # ==================================================================
    def _sample_headway(self, lane: Lane) -> float:
        """指数分布车头时距（泊松到达），按当前时刻的时变需求取率。"""
        rate = self.cfg.demand_at(self.t, lane.direction) * lane.share / 3600.0      # 辆/秒
        if rate <= 0:
            return float("inf")
        return self.rng.expovariate(rate)

    def _spawn(self, lane: Lane) -> None:
        if len(self._lane_lists[lane.key]) >= lane.capacity:
            return                                            # 排队溢出：车辆无法驶入
        v = Vehicle(vid=self._next_vid, lane=lane, s=0.0, speed=13.0, spawn_time=self.t)
        self._next_vid += 1
        self.vehicles.append(v)
        self._lane_lists[lane.key].insert(0, v)               # s=0 最小，保持按里程升序
        self.total_spawned += 1
        if self.measuring:
            self.spawned_measured += 1
            self.lane_stats[lane.key]["hours"] += self.cfg.sim_dt / 3600.0
            self.phase_stats[approach_phase(lane.direction)]["vehicles"] += 1
        # 到达事件用于自适应控制器的「最近 15 秒到达数」
        self._arrivals_trace.append((self.t, approach_phase(lane.direction)))

    def _lane_vehicles(self, lane: Lane) -> list[Vehicle]:
        return self._lane_lists[lane.key]

    def _spawn_vehicles(self) -> None:
        for lane in self.topology.lanes:
            key = lane.key
            while self.t >= self._next_spawn[key]:
                self._spawn(lane)
                self._next_spawn[key] += self._sample_headway(lane)

    # ==================================================================
    # 排队统计
    # ==================================================================
    def lane_queue(self, lane: Lane) -> int:
        """排队车辆数：停车线前、物理上接近停止（速度≈0）的车辆。

        用物理速度而非「是否被信号挡住」判定，避免绿灯一亮的瞬间整条排队
        在控制器视角里“凭空消失”。绿灯放行后，车流从队首加速、依次越过停车线，
        排队才会逐步清零，这才能让自适应配时的 gap-out（清空即切换）正确触发。
        """
        return sum(1 for v in self._lane_lists[lane.key] if not v.passed_stop_line and v.speed < 0.5)

    def queue_by_phase(self) -> dict[int, int]:
        out = {0: 0, 1: 0}
        for ln in self.topology.lanes:
            out[approach_phase(ln.direction)] += self.lane_queue(ln)
        return out

    def queue_by_lane(self) -> dict[tuple[int, str], int]:
        return {ln.key: self.lane_queue(ln) for ln in self.topology.lanes}

    def _arrivals_15s(self) -> dict[int, int]:
        cutoff = self.t - 15.0
        out = {0: 0, 1: 0}
        for t, p in self._arrivals_trace:
            if t >= cutoff:
                out[p] += 1
        if len(self._arrivals_trace) > 4000:
            self._arrivals_trace = [x for x in self._arrivals_trace if x[0] >= cutoff]
        return out

    def _snapshot(self) -> PhaseSnapshot:
        q = self.queue_by_phase()
        return PhaseSnapshot(
            now=self.t,
            queues=q,
            arrivals_15s=self._arrivals_15s(),
            last_green=dict(self._last_green),
            last_cross=dict(self._last_cross),
        )

    # ==================================================================
    # 车辆运动
    # ==================================================================
    def _is_allowed(self, lane: Lane) -> bool:
        """该车道当前是否有通行权。

        * 绿灯：本相位所有转向放行；
        * 黄灯：停车线前尚未越线的车辆必须停车（路口清空原则）；
        * 全红：全部停车。
        """
        if approach_phase(lane.direction) != self.controller.phase:
            return False
        return self.controller.state == PhaseState.GREEN

    def _leader(self, lane: Lane, vehicle: Vehicle) -> tuple[Vehicle | None, float]:
        """返回 (前车, 净间距)。同车道车辆按里程升序，前车即 s 更大的相邻车。"""
        lane_vehicles = self._lane_lists[lane.key]
        i = bisect.bisect_right(lane_vehicles, vehicle.s, key=lambda v: v.s)
        if i < len(lane_vehicles):
            leader = lane_vehicles[i]
            if leader is not vehicle:
                return leader, leader.s - vehicle.s - self.cfg.vehicle_length
        return None, 0.0

    def _stop_barrier(self, lane: Lane, vehicle: Vehicle) -> float | None:
        """若需在停车线前停车，返回到停车线的剩余距离。"""
        if self._is_allowed(lane):
            return None
        dist = lane.path.s_stop - vehicle.s
        return dist if dist > -0.1 else None

    def _update_vehicle(self, vehicle: Vehicle) -> None:
        cfg = self.cfg
        lane = vehicle.lane
        leader, gap = self._leader(lane, vehicle)
        leader_speed = leader.speed if leader else vehicle.speed
        gap_to_leader = gap if leader else None

        v0 = vehicle.desired_speed()
        acc = Vehicle.idm_accel(cfg, vehicle.speed, v0, gap_to_leader, leader_speed)

        # 信号灯约束：把停车线当成一辆静止的「虚拟前车」
        barrier_dist = self._stop_barrier(lane, vehicle)
        held = False
        if barrier_dist is not None:
            held = True
            if barrier_dist <= 0.3:
                # 已压线：允许通过，不再刹车（避免卡在线上）
                barrier_dist = None
            else:
                brake = Vehicle.idm_accel(cfg, vehicle.speed, v0, barrier_dist, 0.0)
                acc = min(acc, brake)

        # 安全间距硬约束：不允许侵入前车车尾
        if leader is not None and gap < 0.5:
            acc = min(acc, -cfg.comfort_decel * 2)
            held = True

        acc = max(acc, -2.0 * cfg.comfort_decel)
        vehicle.accel = acc
        prev_s = vehicle.s
        vehicle.integrate(cfg.sim_dt)

        # 检测是否越过停车线（供自适应控制器的 gap-out 使用）
        if prev_s < lane.path.s_stop <= vehicle.s:
            self._last_cross[approach_phase(lane.direction)] = self.t

        if leader is not None and vehicle.s > leader.s - cfg.vehicle_length:
            # 极端情况防穿模
            vehicle.s = leader.s - cfg.vehicle_length
            vehicle.speed = min(vehicle.speed, leader.speed)

        vehicle.update_queue_state(cfg.sim_dt, self.t, held)

    # ==================================================================
    # 主循环
    # ==================================================================
    def step(self) -> None:
        """推进一个仿真步长 sim_dt。"""
        dt = self.cfg.sim_dt
        now = self.t

        # 1) 预热期结束 -> 开始统计
        if not self.measuring and now >= self.measure_start:
            self.measuring = True

        # 2) 生成车辆
        self._spawn_vehicles()

        # 3) 推进信号机
        prev_state = self.controller.state
        prev_phase = self.controller.phase
        self.controller.update(dt, self._snapshot())
        if prev_state == PhaseState.GREEN and self.controller.state != PhaseState.GREEN:
            self._last_green[prev_phase] = self.controller.stats["per_phase_green"][prev_phase][-1] \
                if self.controller.stats["per_phase_green"][prev_phase] else 0.0

        # 4) 车辆更新（每条车道从队首往后更新，保证前车先更新）
        for lane in self.topology.lanes:
            lane_vehicles = self._lane_lists[lane.key]
            for v in reversed(lane_vehicles):     # 队首（s 最大）在前
                self._update_vehicle(v)

        # 5) 驶离
        for lane in self.topology.lanes:
            lane_vehicles = self._lane_lists[lane.key]
            if not lane_vehicles:
                continue
            # 队首（s 最大）是唯一可能到达终点的车辆，逐个弹出
            while lane_vehicles and lane_vehicles[-1].finished:
                v = lane_vehicles.pop()
                v.exit_time = self.t
                v.close_wait(self.t)
                self.vehicles.remove(v)
                if self.measuring:
                    self._depart_times.append(self.t)
                    self._record_departure(v)
        if self.measuring and len(self._depart_times) > 20000:
            del self._depart_times[:-20000]

        # 6) 采样排队长度
        if self.measuring:
            self._sample_queues()

        # 7) 时间推进
        self.t += dt
        self._series_timer += dt
        if self.measuring and self._series_timer >= 1.0:
            self._series_timer = 0.0
            self._push_series()

    def _record_departure(self, v: Vehicle) -> None:
        phase = approach_phase(v.lane.direction)
        wait = v.total_wait
        self.departed.append({
            "vid": v.vid,
            "dir": v.lane.direction,
            "move": v.lane.move,
            "phase": phase,
            "wait": wait,
            "travel": v.exit_time - v.spawn_time,
        })
        self.lane_stats[v.lane.key]["departed"] += 1
        self.lane_stats[v.lane.key]["wait_total"] += wait
        self.lane_stats[v.lane.key]["wait_samples"] += 1
        self.phase_stats[phase]["departed"] += 1
        self.phase_stats[phase]["wait_total"] += wait
        self.phase_stats[phase]["wait_samples"] += 1

    def _sample_queues(self) -> None:
        for ln in self.topology.lanes:
            q = self.lane_queue(ln)
            st = self.lane_stats[ln.key]
            st["max_queue"] = max(st["max_queue"], q)
            st["queue_sum"] += q
            st["queue_samples"] += 1
            self.max_queue = max(self.max_queue, q)

    def throughput_window(self, seconds: float = 60.0) -> float:
        """最近 seconds 秒的滚动吞吐量（辆/小时）。"""
        if not self.measuring or seconds <= 0:
            return 0.0
        cutoff = self.t - seconds
        recent = sum(1 for t in self._depart_times if t >= cutoff)
        return recent * 3600.0 / seconds

    def _push_series(self) -> None:
        q = self.queue_by_phase()
        self.series["t"].append(round(self.t, 1))
        self.series["queue_ns"].append(q[0])
        self.series["queue_ew"].append(q[1])
        self.series["vehicles"].append(len(self.vehicles))
        self.series["throughput"].append(round(self.throughput_window(), 1))
        waits = [d["wait"] for d in self.departed]
        self.series["mean_wait"].append(round(sum(waits) / len(waits), 2) if waits else 0.0)

    def snapshot(self) -> LiveSnapshot:
        """UI 用的实时状态。"""
        return LiveSnapshot(
            t=self.t,
            phase=self.controller.phase,
            state=self.controller.state,
            green_elapsed=self.controller.green_elapsed,
            queue_by_phase=self.queue_by_phase(),
            queue_by_lane=self.queue_by_lane(),
            vehicles=len(self.vehicles),
            throughput_vph=self.throughput_window(),
        )

    # ==================================================================
    # 运行与结果
    # ==================================================================
    def run(self) -> SimResult:
        while self.t < self.cfg.total_seconds:
            self.step()
        return self.result()

    def result(self) -> SimResult:
        from metrics.statistics import compute_metrics, summarise_controller

        res = SimResult(strategy=self.strategy, config=self.cfg.to_dict())
        res.metrics = compute_metrics(self)
        res.time_series = self.series
        res.controller_stats = summarise_controller(self.controller)
        res.per_lane = {
            f"{d}_{m}": {
                "label": f"dir{d}_{m}",
                "departed": st["departed"],
                "mean_wait": (st["wait_total"] / st["wait_samples"]) if st["wait_samples"] else 0.0,
                "max_queue": st["max_queue"],
                "mean_queue": (st["queue_sum"] / st["queue_samples"]) if st["queue_samples"] else 0.0,
            }
            for (d, m), st in self.lane_stats.items()
        }
        res.per_phase = {
            str(p): {
                "vehicles": st["vehicles"],
                "departed": st["departed"],
                "mean_wait": (st["wait_total"] / st["wait_samples"]) if st["wait_samples"] else 0.0,
            }
            for p, st in self.phase_stats.items()
        }
        return res
