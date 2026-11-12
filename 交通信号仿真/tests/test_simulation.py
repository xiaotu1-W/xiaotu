"""仿真引擎与算法的单元测试。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SimConfig
from controllers.strategies import (ActuatedController, FixedTimeController,
                                    WebsterController, webster_split, create_controller)
from engine import Simulation
from models.track import build_network


class TestConfig(unittest.TestCase):
    def test_defaults(self):
        cfg = SimConfig()
        self.assertEqual(cfg.demand_vph, 600.0)
        self.assertAlmostEqual(cfg.right_ratio, 0.2, places=6)

    def test_invalid_ratio(self):
        with self.assertRaises(ValueError):
            SimConfig(left_ratio=0.7, through_ratio=0.7)

    def test_direction_demand(self):
        cfg = SimConfig(demand_vph=600, demand_ratio_ew=0.5)
        self.assertEqual(cfg.direction_demand(0), 600.0)   # 南北
        self.assertEqual(cfg.direction_demand(1), 300.0)   # 东西

    def test_demand_at_profile(self):
        cfg = SimConfig(demand_vph=540, demand_profile=((0, 900, 0.3), (700, 270, 3.0)))
        self.assertEqual(cfg.demand_at(0, 0), 900.0)
        self.assertEqual(cfg.demand_at(0, 1), 270.0)
        self.assertEqual(cfg.demand_at(800, 0), 270.0)
        self.assertEqual(cfg.demand_at(800, 1), 810.0)


class TestTopology(unittest.TestCase):
    def setUp(self):
        self.cfg = SimConfig()
        self.topo = build_network(self.cfg)

    def test_lane_count(self):
        # 4 个进口道 × 3 车道 = 12 条车道
        self.assertEqual(len(self.topo.lanes), 12)

    def test_paths_have_stop(self):
        for ln in self.topo.lanes:
            self.assertGreater(ln.path.s_stop, 0)
            self.assertGreater(ln.path.length, ln.path.s_stop)

    def test_path_position(self):
        ln = self.topo.lanes[0]
        x0, z0 = ln.path.position(0.0)
        x1, z1 = ln.path.position(ln.path.length)
        self.assertGreater((x1 - x0) ** 2 + (z1 - z0) ** 2, 100.0)  # 轨迹足够长


class TestWebster(unittest.TestCase):
    def test_split_sums_to_effective(self):
        cycle, split = webster_split({0: 400, 1: 200}, saturation_flow=1800, lost_time=10)
        self.assertAlmostEqual(sum(split.values()), max(cycle - 10, 4), places=1)

    def test_equal_flow_equal_split(self):
        cycle, split = webster_split({0: 300, 1: 300}, saturation_flow=1800, lost_time=10)
        self.assertAlmostEqual(split[0], split[1], places=2)


class TestControllers(unittest.TestCase):
    def test_fixed_constant_green(self):
        cfg = SimConfig(fixed_green=25)
        c = FixedTimeController(cfg)
        self.assertEqual(c.desired_green(0, None), 25)

    def test_factory(self):
        self.assertIsInstance(create_controller("fixed", SimConfig()), FixedTimeController)
        self.assertIsInstance(create_controller("actuated", SimConfig()), ActuatedController)
        self.assertIsInstance(create_controller("webster", SimConfig()), WebsterController)
        with self.assertRaises(KeyError):
            create_controller("nope", SimConfig())


class TestSimulation(unittest.TestCase):
    def _run(self, strategy="fixed", demand=600, warmup=60, measure=120):
        cfg = SimConfig(demand_vph=demand, warmup_seconds=warmup, measure_seconds=measure, seed=7)
        return Simulation(cfg, strategy).run()

    def test_deterministic(self):
        r1 = self._run()
        r2 = self._run()
        self.assertEqual(r1.metrics["mean_wait"], r2.metrics["mean_wait"])
        self.assertEqual(r1.metrics["throughput_vph"], r2.metrics["throughput_vph"])

    def test_metrics_present(self):
        m = self._run().metrics
        for key in ("mean_wait", "p95_wait", "max_wait", "max_queue", "throughput_vph",
                    "service_ratio", "mean_cycle"):
            self.assertIn(key, m)

    def test_service_ratio_plausible(self):
        m = self._run(demand=600).metrics
        self.assertGreater(m["service_ratio"], 0.0)
        self.assertLessEqual(m["service_ratio"], 1.5)

    def test_actuated_adapts_to_imbalance(self):
        """不均衡车流下，自适应配时应给繁忙的南北相位更多绿灯。"""
        cfg = SimConfig(demand_vph=700, demand_ratio_ew=0.3, warmup_seconds=120, measure_seconds=300)
        res = Simulation(cfg, "actuated").run()
        self.assertGreater(res.controller_stats["green_ns_mean"],
                           res.controller_stats["green_ew_mean"])

    def test_webster_best_under_steady(self):
        """稳态不均衡需求下，Webster 的平均等待应低于固定配时。"""
        cfg = SimConfig(demand_vph=700, demand_ratio_ew=0.3, warmup_seconds=120, measure_seconds=300)
        fixed = Simulation(cfg, "fixed").run().metrics["mean_wait"]
        webster = Simulation(cfg, "webster").run().metrics["mean_wait"]
        self.assertLess(webster, fixed)

    def test_tidal_adaptive_beats_webster(self):
        """潮汐车流下，自适应应优于按平均需求计算的 Webster。"""
        profile = ((0, 900, 0.3), (700, 270, 3.0), (1400, 450, 1.0))
        kwargs = dict(demand_vph=540, demand_ratio_ew=1.0, demand_profile=profile,
                      warmup_seconds=150, measure_seconds=300)
        act = Simulation(SimConfig(**kwargs), "actuated").run().metrics["mean_wait"]
        web = Simulation(SimConfig(**kwargs), "webster").run().metrics["mean_wait"]
        self.assertLess(act, web)


class TestStorage(unittest.TestCase):
    def test_sqlite_roundtrip(self):
        from storage import StrategyRepository

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "test.db")
            repo = StrategyRepository({"backend": "sqlite", "path": path})
            cfg = SimConfig(demand_vph=600)
            metrics = {"mean_wait": 12.3, "throughput_vph": 2000.0, "arrivals": 100, "departed": 95}
            rid = repo.insert_run("actuated", cfg, metrics)
            self.assertIsInstance(rid, int)
            rows = repo.list_runs(strategy="actuated")
            self.assertEqual(len(rows), 1)
            self.assertAlmostEqual(rows[0]["mean_wait"], 12.3)
            repo.close()


if __name__ == "__main__":
    unittest.main()
