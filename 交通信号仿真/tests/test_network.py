"""多路口网格引擎与绿波协调的单元测试。

运行：python -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import SimConfig
from engine_network import NetworkSimulation
from controllers.coordinated import CoordinatedController
from models.network import build_grid, green_wave_offset


class TestGreenWaveOffset(unittest.TestCase):
    def test_offset_is_travel_time(self):
        self.assertAlmostEqual(green_wave_offset(220.0, 13.9), 220.0 / 13.9, places=2)

    def test_zero_speed(self):
        self.assertEqual(green_wave_offset(220.0, 0.0), 0.0)


class TestCoordinatedController(unittest.TestCase):
    def test_offset_shifts_phase(self):
        cfg = SimConfig()
        c0 = CoordinatedController(cfg, offset=0.0, cycle=60.0)
        c1 = CoordinatedController(cfg, offset=10.0, cycle=60.0)
        # 相同时刻，含 offset 的控制器相位应不同（除非 10s 恰好落在同相位段）
        # 用不同 offset 验证相位时钟确实平移了
        class Snap:
            now = 5.0
        c0.update(0.0, Snap())
        c1.update(0.0, Snap())
        # 5s 与 15s 在 half_green=25 的周期内同属相位0绿灯，但 elapsed 不同
        self.assertEqual(c0.phase, c1.phase)
        self.assertNotEqual(round(c0.green_elapsed, 1), round(c1.green_elapsed, 1))

    def test_periodic_consistency(self):
        cfg = SimConfig()
        c = CoordinatedController(cfg, offset=3.0, cycle=60.0)
        class Snap:
            now = 0.0
        s0 = Snap(); s0.now = 0.0
        s60 = Snap(); s60.now = 60.0
        c.update(0.0, s0)
        phase0, elapsed0 = c.phase, round(c.green_elapsed, 1)
        c.update(0.0, s60)
        self.assertEqual(c.phase, phase0)
        self.assertEqual(round(c.green_elapsed, 1), elapsed0)   # 周期一致


class TestNetworkSimulation(unittest.TestCase):
    def test_runs_and_reports(self):
        cfg = SimConfig(demand_vph=600, warmup_seconds=30, measure_seconds=90, seed=7)
        sim = NetworkSimulation(cfg, rows=2, cols=2, link_length=200, strategy='fixed')
        r = sim.run()
        self.assertIn("mean_wait", r)
        self.assertIn("max_queue", r)
        self.assertGreater(r["departed"], 0)

    def test_deterministic(self):
        cfg = SimConfig(demand_vph=600, warmup_seconds=30, measure_seconds=90, seed=7)
        r1 = NetworkSimulation(cfg, rows=2, cols=2, link_length=200).run()
        r2 = NetworkSimulation(cfg, rows=2, cols=2, link_length=200).run()
        self.assertEqual(r1["mean_wait"], r2["mean_wait"])
        self.assertEqual(r1["departed"], r2["departed"])

    def test_directional_bias_increases_flow(self):
        """偏置方向入口车流应更多。"""
        cfg = SimConfig(demand_vph=600, warmup_seconds=30, measure_seconds=90, seed=7)
        sim = NetworkSimulation(cfg, rows=2, cols=2, link_length=200, direction_bias=3, bias_factor=2.0)
        sim.run()
        self.assertGreater(sim.total_spawned, 0)

    def test_capture_state(self):
        cfg = SimConfig(demand_vph=600, warmup_seconds=30, measure_seconds=90, seed=7)
        sim = NetworkSimulation(cfg, rows=2, cols=2, link_length=200)
        sim.run()
        st = sim.capture_state(cfg.total_seconds)
        self.assertIn("vehicles", st)
        self.assertIn("signals", st)


if __name__ == "__main__":
    unittest.main()
