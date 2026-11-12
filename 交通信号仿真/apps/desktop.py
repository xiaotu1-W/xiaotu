"""Pygame 桌面仿真界面。

    python main.py                      # 启动桌面仿真
    python main.py --screenshot out.png # 无界面渲染一帧并保存（CI/文档截图用）

功能：
* 实时渲染十字路口、三车道、转向轨迹、信号灯、车辆；
* 右侧面板显示策略、相位、排队、吞吐、平均等待等实时指标；
* 交互：空格暂停/单步、S 切换策略、D 循环车流量、R 重置、ESC 退出；
* 渲染与仿真解耦：用固定时间步进，保证任何机器上结果一致。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import pygame

from config import SimConfig, THEME, WINDOW_SIZE, FPS, approach_phase, DIR_NAMES, MOVE_NAMES
from engine import Simulation
from controllers.strategies import STRATEGIES, create_controller
from models.track import DIR_VECTORS

# --------------------------------------------------------------------------
# 字体（中文字体回退）
# --------------------------------------------------------------------------
_FONT_PATHS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
]


def load_fonts() -> tuple:
    """加载中文字体，返回 (title, body, small)。"""
    path = next((p for p in _FONT_PATHS if os.path.exists(p)), None)
    if path:
        title = pygame.font.Font(path, 22)
        body = pygame.font.Font(path, 17)
        small = pygame.font.Font(path, 14)
        big = pygame.font.Font(path, 34)
    else:
        title = pygame.font.Font(None, 24)
        body = pygame.font.Font(None, 18)
        small = pygame.font.Font(None, 15)
        big = pygame.font.Font(None, 36)
    return title, body, small, big


# --------------------------------------------------------------------------
# 坐标变换
# --------------------------------------------------------------------------
class Viewport:
    """世界坐标(x,z) -> 屏幕坐标。z 向下，与屏幕 y 一致。"""

    def __init__(self, cx: float, cy: float, scale: float) -> None:
        self.cx = cx
        self.cy = cy
        self.scale = scale

    def to_screen(self, x: float, z: float) -> tuple[int, int]:
        return (int(self.cx + x * self.scale), int(self.cy + z * self.scale))


# --------------------------------------------------------------------------
# 绘制
# --------------------------------------------------------------------------
def draw_arrow(surface, center, angle_deg, length, color):
    """画一个箭头指示车道行驶方向。"""
    import math

    rad = math.radians(angle_deg)
    tip = (center[0] + math.cos(rad) * length, center[1] + math.sin(rad) * length)
    base = (center[0] - math.cos(rad) * length * 0.4, center[1] - math.sin(rad) * length * 0.4)
    pygame.draw.line(surface, color, base, tip, 2)
    # 箭头两翼
    for d in (150, -150):
        r = math.radians(angle_deg + d)
        wing = (tip[0] + math.cos(r) * length * 0.35, tip[1] + math.sin(r) * length * 0.35)
        pygame.draw.line(surface, color, tip, wing, 2)


def draw_car(surface, center, heading, length, width, color):
    """绘制带车窗、车灯和柔和阴影的朝向车辆图标。"""
    import math
    cx, cy = center
    hx, hy = heading
    angle = math.atan2(hy, hx)
    ux, uy = math.cos(angle), math.sin(angle)
    px, py = -uy, ux

    def point(along, across):
        return (cx + ux * along + px * across, cy + uy * along + py * across)

    length, width = max(8, length), max(5, width)
    body_offsets = [(length * .50, -width * .34), (length * .34, -width * .50),
                    (-length * .40, -width * .50), (-length * .50, -width * .30),
                    (-length * .50, width * .30), (-length * .40, width * .50),
                    (length * .34, width * .50), (length * .50, width * .34)]
    body = [point(a, b) for a, b in body_offsets]
    pygame.draw.polygon(surface, (5, 9, 16), [point(a, b + 1.5) for a, b in body_offsets])
    pygame.draw.polygon(surface, color, body)
    pygame.draw.polygon(surface, (215, 231, 242), body, 1)
    glass = [point(length*.19, -width*.31), point(length*.31, -width*.31),
             point(length*.31, width*.31), point(length*.19, width*.31)]
    pygame.draw.polygon(surface, (177, 211, 229), glass)
    for side in (-1, 1):
        pygame.draw.circle(surface, (255, 244, 181), point(length*.39, side*width*.28), max(1, int(width*.09)))
        pygame.draw.circle(surface, (255, 103, 112), point(-length*.40, side*width*.28), max(1, int(width*.08)))


def draw_intersection(surface, sim: Simulation, vp: Viewport) -> None:
    """绘制路口。"""
    cfg = sim.cfg
    surface.fill(THEME["bg"])

    # 道路：四条，用路面颜色矩形
    hw = cfg.road_half_width
    rl = cfg.road_length
    # 竖向道路（南北）
    p1 = vp.to_screen(-hw, -rl)
    p2 = vp.to_screen(hw, rl)
    pygame.draw.rect(surface, THEME["asphalt"], (*p1, p2[0] - p1[0], p2[1] - p1[1]))
    # 横向道路（东西）
    p1 = vp.to_screen(-rl, -hw)
    p2 = vp.to_screen(rl, hw)
    pygame.draw.rect(surface, THEME["asphalt"], (*p1, p2[0] - p1[0], p2[1] - p1[1]))

    # 车道分隔线（每条道路 2 条白虚线，分隔 3 车道）
    for axis in (0, 1):  # 0=竖向道路, 1=横向道路
        for off in (-hw / 3, hw / 3):
            pts = []
            for t in range(-int(rl), int(rl), 4):
                if axis == 0:
                    x, z = off, t
                else:
                    x, z = t, off
                pts.append(vp.to_screen(x, z))
            # 画虚线
            for i in range(0, len(pts) - 1, 2):
                pygame.draw.line(surface, THEME["lane_mark"], pts[i], pts[i + 1], 2)

    # 中央黄色双实线（示意路口中心）
    center = vp.to_screen(0, 0)
    pygame.draw.circle(surface, THEME["yellow"], center, 3)

    # 停车线（每个进口道 3 条车道各一条，简化为每个进口一条粗白线）
    for d in range(4):
        # 停车线在距中心 stop_line_offset 处，垂直于行驶方向
        fwd = DIR_VECTORS[d]
        # 法向（垂直于行驶方向）
        nx, nz = fwd[1], -fwd[0]
        stop = cfg.stop_line_offset
        a = vp.to_screen(-fwd[0] * stop + nx * hw, -fwd[1] * stop + nz * hw)
        b = vp.to_screen(-fwd[0] * stop - nx * hw, -fwd[1] * stop - nz * hw)
        pygame.draw.line(surface, THEME["stop_line"], a, b, 3)

    # 信号灯（每个进口道一个，放在停车线外侧角上）
    for d in range(4):
        fwd = DIR_VECTORS[d]
        nx, nz = fwd[1], -fwd[0]
        lx = -fwd[0] * (cfg.stop_line_offset + 2) + nx * (hw + 4)
        lz = -fwd[1] * (cfg.stop_line_offset + 2) + nz * (hw + 4)
        pos = vp.to_screen(lx, lz)
        color = THEME["green"] if sim.controller.state == "green" and approach_phase(d) == sim.controller.phase \
            else THEME["yellow"] if sim.controller.state == "yellow" and approach_phase(d) == sim.controller.phase \
            else THEME["red"]
        pygame.draw.circle(surface, (20, 24, 32), pos, 9)
        pygame.draw.circle(surface, color, pos, 7)

    # 车道方向箭头（示意）
    for d in range(4):
        fwd = DIR_VECTORS[d]
        for move, angle_off in (("left", -90), ("through", 0), ("right", 90)):
            from math import atan2, degrees
            base_angle = degrees(atan2(fwd[1], fwd[0]))
            ang = base_angle + angle_off
            offs = {"left": -hw / 2, "through": 0.0, "right": hw / 2}
            off = offs[move]
            nx, nz = fwd[1], -fwd[0]
            pos = vp.to_screen(-fwd[0] * (rl - 14) + nx * off, -fwd[1] * (rl - 14) + nz * off)
            draw_arrow(surface, pos, ang, 10, THEME["text_dim"])

    # 车辆
    for v in sim.vehicles:
        x, z = v.position
        pos = vp.to_screen(x, z)
        hx, hz = v.heading
        import math
        ang = math.degrees(math.atan2(hz, hx))
        length = cfg.vehicle_length * vp.scale
        width = 1.9 * vp.scale
        color = {"through": THEME["car_through"], "left": THEME["car_left"], "right": THEME["car_right"]}[v.lane.move]
        if v.queued:
            color = THEME["car_queued"]
        draw_car(surface, pos, (hx, hz), length, width, color)


def draw_panel(surface, sim: Simulation, fonts, offset_x: int, speed: float = 1.0) -> None:
    """右侧信息面板。"""
    title, body, small, big = fonts
    x = offset_x
    pygame.draw.rect(surface, THEME["panel"], (x, 0, surface.get_width() - x, surface.get_height()))
    pygame.draw.line(surface, THEME["panel_border"], (x, 0), (x, surface.get_height()), 2)

    c = sim.controller
    q = sim.queue_by_phase()
    line = 24

    def put(font, text, color=THEME["text"], y=None):
        nonlocal line
        yy = line if y is None else y
        surface.blit(font.render(text, True, color), (x + 18, yy))
        line = yy + font.get_height() + 8

    put(title, "交通信号配时仿真", THEME["accent"])
    line += 6

    put(body, f"策略: {c.label}", THEME["fixed"] if c.name == "fixed" else THEME["actuated"] if c.name == "actuated" else THEME["webster"])
    state_color = {"green": THEME["green"], "yellow": THEME["yellow"], "all_red": THEME["red"]}[c.state]
    put(body, f"相位: {c.phase_name}  [{c.state.upper()}]", state_color)
    put(body, f"绿灯已用: {c.green_elapsed:.1f}s / 计划 {c.green_planned:.1f}s")
    put(small, f"仿真时间: {sim.t:.0f}s ({'统计期' if sim.measuring else '预热期'})")
    put(body, f"倍速: ×{speed:g}", THEME["accent"] if speed > 1 else THEME["text_dim"])

    line += 8
    put(body, "—— 实时排队 ——")
    put(body, f"南北相位: {q[0]} 辆", THEME["car_through"])
    put(body, f"东西相位: {q[1]} 辆", THEME["car_right"])

    line += 8
    put(body, "—— 实时指标 ——")
    put(body, f"在场车辆: {len(sim.vehicles)}")
    put(body, f"滚动吞吐量: {sim.throughput_window():.0f} 辆/时")
    if sim.departed:
        waits = [d['wait'] for d in sim.departed]
        put(body, f"平均等待: {sum(waits)/len(waits):.2f}s")

    line += 8
    put(small, f"车流量: {sim.cfg.demand_vph:.0f} 辆/时/进口道", THEME["text_dim"])
    if sim.cfg.demand_profile:
        put(small, "（潮汐车流模式）", THEME["text_dim"])

    line += 10
    put(small, "操作:", THEME["accent"])
    put(small, "  空格 = 暂停/单步")
    put(small, "  + / - = 加速 / 减速")
    put(small, "  S = 切换策略")
    put(small, "  D = 循环车流量")
    put(small, "  R = 重置仿真")
    put(small, "  ESC = 退出")


def draw_frame(surface, sim: Simulation, fonts, vp: Viewport, panel_x: int, speed: float = 1.0) -> None:
    draw_intersection(surface, sim, vp)
    draw_panel(surface, sim, fonts, panel_x, speed)


# ==========================================================================
# 多路口网格渲染（NetworkSimulation）
# ==========================================================================
NET_TRAVEL = {0: (0.0, 1.0), 1: (-1.0, 0.0), 2: (0.0, -1.0), 3: (1.0, 0.0)}
# 与 engine_network.APPROACH_TRAVEL 一致：(行, 列) 位移
NET_APPROACH_TRAVEL = {0: (1, 0), 1: (0, -1), 2: (-1, 0), 3: (0, 1)}


def net_center(nsim, i: int, j: int, vp: Viewport) -> tuple[int, int]:
    """路口 (i,j) 中心的屏幕坐标。"""
    x = (j - (nsim.cols - 1) / 2) * nsim.link_length
    z = (i - (nsim.rows - 1) / 2) * nsim.link_length
    return vp.to_screen(x, z)


def draw_network(surface, nsim, vp: Viewport) -> None:
    """绘制多路口网格：路段、路口、信号灯、车辆。"""
    surface.fill(THEME["bg"])
    link = nsim.link_length
    half_road = 10.5

    # 背景网格增加空间感，中心区域保持简洁以突出道路。
    for gx in range(24, surface.get_width() - 400, 32):
        pygame.draw.line(surface, (13, 21, 34), (gx, 0), (gx, surface.get_height()), 1)
    for gy in range(16, surface.get_height(), 32):
        pygame.draw.line(surface, (13, 21, 34), (0, gy), (surface.get_width() - 400, gy), 1)

    # ---- 1. 路段（两条平行车道带）----
    road_w = int(half_road * 2 * vp.scale)
    for i in range(nsim.rows):
        for j in range(nsim.cols):
            # 东西向路段：从 (i,j) 向东到 (i,j+1)
            if j + 1 < nsim.cols:
                a = net_center(nsim, i, j, vp)
                b = net_center(nsim, i, j + 1, vp)
                pygame.draw.line(surface, (10, 15, 24), a, b, road_w + 6)
                pygame.draw.line(surface, (42, 51, 65), a, b, road_w)
                pygame.draw.line(surface, (79, 91, 108), a, b, 1)
            # 南北向路段：从 (i,j) 向南到 (i+1,j)
            if i + 1 < nsim.rows:
                a = net_center(nsim, i, j, vp)
                b = net_center(nsim, i + 1, j, vp)
                pygame.draw.line(surface, (10, 15, 24), a, b, road_w + 6)
                pygame.draw.line(surface, (42, 51, 65), a, b, road_w)
                pygame.draw.line(surface, (79, 91, 108), a, b, 1)

    # ---- 1b. 边界引道：从边界路口向外延伸一个路段，承接边界车流 ----
    # 车辆来自上游一格 (i-di, j-dj)，故引道朝「旅行方向的反向」延伸。
    for i in range(nsim.rows):
        for j in range(nsim.cols):
            c = net_center(nsim, i, j, vp)
            for d in range(4):
                di, dj = NET_APPROACH_TRAVEL[d]
                ui, uj = i - di, j - dj
                if 0 <= ui < nsim.rows and 0 <= uj < nsim.cols:
                    continue                     # 上游在网格内，已有内部路段
                tx, tz = NET_TRAVEL[d]
                end = (c[0] - tx * nsim.link_length * vp.scale,
                       c[1] - tz * nsim.link_length * vp.scale)
                pygame.draw.line(surface, (10, 15, 24), c, end, road_w + 6)
                pygame.draw.line(surface, (42, 51, 65), c, end, road_w)
                pygame.draw.line(surface, (79, 91, 108), c, end, 1)

    # ---- 2. 路口方块 + 信号灯 ----
    r = int(max(6, half_road * vp.scale * 0.9))
    for i in range(nsim.rows):
        for j in range(nsim.cols):
            c = net_center(nsim, i, j, vp)
            pygame.draw.rect(surface, (10, 15, 24),
                             (c[0] - r - 2, c[1] - r - 2, r * 2 + 4, r * 2 + 4), border_radius=5)
            pygame.draw.rect(surface, (54, 64, 80),
                             (c[0] - r, c[1] - r, r * 2, r * 2), border_radius=4)
            # 路口人行横道以短白条显示在每个进口道边缘。
            stripe = max(2, int(2.2 * vp.scale))
            gap = max(2, int(3.2 * vp.scale))
            for k in range(4):
                off = (k - 1.5) * (stripe + gap)
                pygame.draw.line(surface, (173, 184, 198),
                                 (c[0] + off, c[1] - r), (c[0] + off, c[1] - r - stripe * 2), stripe)
                pygame.draw.line(surface, (173, 184, 198),
                                 (c[0] + off, c[1] + r), (c[0] + off, c[1] + r + stripe * 2), stripe)
            ctrl = nsim.controllers[(i, j)]
            # 东西方向灯（左）与南北方向灯（上）
            col_ns = {"green": THEME["green"], "yellow": THEME["yellow"],
                      "all_red": THEME["red"]}[ctrl.state] if ctrl.phase == 0 else THEME["red"]
            col_ew = {"green": THEME["green"], "yellow": THEME["yellow"],
                      "all_red": THEME["red"]}[ctrl.state] if ctrl.phase == 1 else THEME["red"]
            pygame.draw.circle(surface, (16, 20, 28), (c[0], c[1] - r - 7), 5)
            pygame.draw.circle(surface, col_ns, (c[0], c[1] - r - 7), 4)
            pygame.draw.circle(surface, (16, 20, 28), (c[0] - r - 7, c[1]), 5)
            pygame.draw.circle(surface, col_ew, (c[0] - r - 7, c[1]), 4)

    # ---- 3. 车辆 ----
    for v in nsim.vehicles:
        cx, cz = nsim._link_start(v.from_i, v.from_j, v.dir)
        dv = NET_TRAVEL[v.dir]
        sx, sz = vp.to_screen(cx + dv[0] * v.s, cz + dv[1] * v.s)
        length = max(6, nsim.cfg.vehicle_length * vp.scale)
        width = max(4, 1.9 * vp.scale)
        color = THEME["car_queued"] if v.queued else (
            THEME["car_through"] if v.turn == "through" else THEME["car_left"])
        dx, dy = NET_TRAVEL[v.dir]
        draw_car(surface, (sx, sz), (dx, dy), length, width, color)


def draw_network_panel(surface, nsim, fonts, panel_x: int, strategy: str,
                       coordinated: bool, demand: float, speed: float = 1.0,
                       actual_speed: float = 1.0) -> None:
    """多路口信息面板。"""
    title, body, small, big = fonts
    x = panel_x
    pygame.draw.rect(surface, THEME["panel"], (x, 0, surface.get_width() - x, surface.get_height()))
    pygame.draw.line(surface, THEME["panel_border"], (x, 0), (x, surface.get_height()), 2)

    line = 24

    def put(font, text, color=THEME["text"]):
        nonlocal line
        surface.blit(font.render(text, True, color), (x + 18, line))
        line += font.get_height() + 8

    put(title, "多路口网格仿真", THEME["accent"])
    line += 6
    put(body, f"网格: {nsim.rows} × {nsim.cols}")
    put(body, f"模式: {'绿波协调' if coordinated else STRATEGIES.get(strategy, strategy)}",
        THEME["car_right"] if coordinated else THEME["actuated"])
    # 倍速高亮显示
    speed_color = THEME["accent"] if speed > 1 else THEME["text_dim"]
    put(body, f"倍速: ×{speed:g}  实际 ≈ ×{actual_speed:.1f}", speed_color)
    total = max(1.0, nsim.cfg.total_seconds)
    prog = min(1.0, nsim.t / total)
    if prog >= 1.0:
        put(small, f"进度: 100%  实验已完成 ✓ · 按 R 重跑", THEME["accent"])
    else:
        put(small, f"进度: {prog*100:.0f}%  ({nsim.t:.0f}/{total:.0f}s)")
    # 进度条
    bar_w = 340
    pygame.draw.rect(surface, (30, 40, 58), (x + 18, line, bar_w, 6), border_radius=3)
    pygame.draw.rect(surface, THEME["accent"], (x + 18, line, int(bar_w * prog), 6), border_radius=3)
    line += 16
    put(small, f"仿真时间: {nsim.t:.0f}s ({'统计期' if nsim.measuring else '预热期'})")

    line += 8
    put(body, "—— 路网指标 ——")
    put(body, f"在场车辆: {len(nsim.vehicles)}")
    put(body, f"总排队: {nsim.total_queue()} 辆", THEME["car_queued"])
    put(body, f"滚动吞吐: {nsim.throughput_window():.0f} 辆/时")
    if nsim.departed:
        put(body, f"已驶离: {nsim.departed} 辆")

    # 各路口灯色一览
    line += 8
    put(body, "—— 路口信号 ——")
    for i in range(min(nsim.rows, 3)):
        cells = []
        for j in range(min(nsim.cols, 4)):
            c = nsim.controllers[(i, j)]
            mark = "绿" if c.state == "green" else ("黄" if c.state == "yellow" else "红")
            cells.append(mark)
        put(small, f"  行{i}: " + " ".join(cells), THEME["text_dim"])

    line += 8
    put(small, f"车流量: {demand:.0f} 辆/时/进口道", THEME["text_dim"])
    line += 10
    put(small, "操作:", THEME["accent"])
    put(small, "  空格 = 暂停/单步")
    put(small, "  + / - = 加速 / 减速")
    put(small, "  S = 切换策略")
    put(small, "  D = 循环车流量")
    put(small, "  C = 绿波协调开/关")
    put(small, "  R = 重置仿真")
    put(small, "  ESC = 退出")


def draw_dashboard(surface, sim, fonts, offset_x: int, speed: float = 1.0) -> None:
    """为单路口提供更清晰的层级：控制状态、核心指标、实验进度和图例。"""
    title, body, small, big = fonts
    x, width = offset_x, surface.get_width() - offset_x
    pygame.draw.rect(surface, THEME["panel"], (x, 0, width, surface.get_height()))
    pygame.draw.line(surface, THEME["panel_border"], (x, 0), (x, surface.get_height()), 2)
    c = sim.controller
    q = sim.queue_by_phase()
    y = 24

    def text(font, value, color=THEME["text"], indent=18):
        nonlocal y
        surface.blit(font.render(value, True, color), (x + indent, y))
        y += font.get_height() + 7

    def section(label):
        nonlocal y
        y += 7
        pygame.draw.line(surface, THEME["panel_border"], (x + 18, y), (x + width - 18, y), 1)
        y += 10
        text(small, label, THEME["accent"])

    text(title, "路口仿真实验", THEME["accent"])
    text(small, f"控制策略  ·  {c.label}", THEME["text_dim"])
    state_color = {"green": THEME["green"], "yellow": THEME["yellow"], "all_red": THEME["red"]}[c.state]
    text(body, f"{c.phase_name}  /  {c.state.upper()}", state_color)
    text(small, f"绿灯 {c.green_elapsed:.1f}s  ·  计划 {c.green_planned:.1f}s", THEME["text_dim"])
    section("实时交通")
    text(body, f"南北排队      {q[0]} 辆", THEME["car_through"])
    text(body, f"东西排队      {q[1]} 辆", THEME["car_right"])
    text(body, f"在场车辆      {len(sim.vehicles)} 辆")
    text(body, f"滚动吞吐      {sim.throughput_window():.0f} 辆/时")
    waits = [d["wait"] for d in sim.departed]
    text(body, f"平均等待      {sum(waits) / len(waits):.1f}s" if waits else "平均等待      —")
    section("实验进度")
    text(small, f"仿真时间 {sim.t:.0f}s  ·  {'统计期' if sim.measuring else '预热期'}", THEME["text_dim"])
    progress = min(1.0, sim.t / max(1.0, sim.cfg.total_seconds))
    bx, by, bw = x + 18, y + 2, width - 36
    pygame.draw.rect(surface, (30, 40, 58), (bx, by, bw, 8), border_radius=4)
    pygame.draw.rect(surface, THEME["accent"], (bx, by, int(bw * progress), 8), border_radius=4)
    y += 20
    text(small, f"需求 {sim.cfg.demand_vph:.0f} 辆/时/进口道   ·   倍速 ×{speed:g}", THEME["text_dim"])
    section("图例与操作")
    for label, color in (("直行", THEME["car_through"]), ("左转", THEME["car_left"]),
                         ("右转", THEME["car_right"]), ("排队", THEME["car_queued"])):
        pygame.draw.circle(surface, color, (x + 26, y + 8), 5)
        text(small, label, THEME["text_dim"], indent=40)
    text(small, "空格 暂停   ·   S 策略   ·   D 车流", THEME["text_dim"])
    text(small, "+ / - 倍速   ·   R 重置   ·   ESC 退出", THEME["text_dim"])


# --------------------------------------------------------------------------
# 主循环
# --------------------------------------------------------------------------
DEMANDS = [300.0, 600.0, 900.0, 1200.0]
# 倍速档位：1 倍速 = 实时；数值为「每 1 秒真实时间推进的仿真秒数」
SPEEDS = [1, 2, 5, 10, 25, 50, 100]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pygame 交通信号仿真")
    parser.add_argument("--screenshot", metavar="PATH", help="无界面渲染若干帧并保存（用 ; 分隔多帧路径）")
    parser.add_argument("--grid", default="3x3", help="网格尺寸，如 3x3（1x1 为单路口）")
    parser.add_argument("--link", type=float, default=220.0, help="路段长度（米）")
    parser.add_argument("--strategy", default="actuated", choices=list(STRATEGIES))
    parser.add_argument("--coordinated", action="store_true", default=True, help="启用绿波协调")
    parser.add_argument("--no-coordinated", dest="coordinated", action="store_false")
    parser.add_argument("--demand", type=float, default=600.0)
    parser.add_argument("--speed", type=float, default=1.0, help="初始倍速（1=实时，数值越大越快）")
    args = parser.parse_args(argv)

    try:
        gr, gc = args.grid.lower().split("x")
        rows, cols = int(gr), int(gc)
    except Exception:
        rows, cols = 3, 3

    use_network = (rows * cols) > 1
    headless = args.screenshot is not None
    if headless:
        os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

    pygame.init()
    if headless:
        surface = pygame.Surface(WINDOW_SIZE)
    else:
        surface = pygame.display.set_mode(WINDOW_SIZE)
        pygame.display.set_caption(f"交通信号配时仿真系统 · {rows}x{cols} 网格")
    clock = pygame.time.Clock()
    fonts = load_fonts()

    # 视口：网格铺满左侧区域
    panel_x = WINDOW_SIZE[0] - 360
    view_w = panel_x - 40
    view_h = WINDOW_SIZE[1] - 40
    if use_network:
        span_x = max(1, cols) * args.link
        span_z = max(1, rows) * args.link
        scale = min(view_w / (span_x * 1.15), view_h / (span_z * 1.15))
    else:
        scale = min(view_w / (2 * cfg.road_length * 1.12), view_h / (2 * cfg.road_length * 1.12)) if 'cfg' in locals() else 3.4
    vp = Viewport(20 + view_w / 2, WINDOW_SIZE[1] / 2, scale)

    cfg = SimConfig(demand_vph=args.demand, warmup_seconds=60, measure_seconds=300)

    # ---- 构建仿真对象 ----
    if use_network:
        from engine_network import NetworkSimulation

        def build(coord, strategy, demand):
            return NetworkSimulation(
                SimConfig(demand_vph=demand, warmup_seconds=60, measure_seconds=300),
                rows=rows, cols=cols, link_length=args.link,
                strategy=strategy, coordinated=coord,
                direction_bias=3, bias_factor=2.5,
            )

        nsim = build(args.coordinated, args.strategy, args.demand)
        sim = None
    else:
        from engine import Simulation

        sim = Simulation(cfg, args.strategy)
        nsim = None

    strategy_index = list(STRATEGIES).index(args.strategy)
    demand_index = DEMANDS.index(args.demand) if args.demand in DEMANDS else 0
    coordinated = args.coordinated
    # 倍速：>1 时每帧推进更多仿真步，用于「快速跑完实验」
    speed = float(args.speed) if args.speed and args.speed > 0 else 1.0
    speed_index = min(range(len(SPEEDS)), key=lambda i: abs(SPEEDS[i] - speed))
    paused = False
    running = True
    accumulator = 0.0
    # 单帧最多推进的仿真步数，避免高倍速时窗口卡死
    MAX_STEPS_PER_FRAME = 4000
    # 实测倍速（仿真秒 / 真实秒），用于显示「实际 ≈ ×N」
    _real_mark = time.perf_counter()
    _sim_mark = nsim.t if use_network else sim.t
    actual_speed = 1.0

    def rebuild(strategy=None, demand=None):
        nonlocal nsim, sim, coordinated
        st = strategy or (nsim.strategy if use_network else sim.strategy)
        dm = demand or (nsim.cfg.demand_vph if use_network else sim.cfg.demand_vph)
        if use_network:
            nsim = build(coordinated, st, dm)
        else:
            sim = Simulation(SimConfig(demand_vph=dm, warmup_seconds=60, measure_seconds=300), st)

    # ---- 无界面截图模式 ----
    if headless:
        paths = args.screenshot.split(";")
        # 先预热让路网有车流，再逐帧截图
        for _ in range(int(150 / cfg.sim_dt)):
            if use_network:
                nsim.step()
            else:
                sim.step()
        for i in range(len(paths)):
            for _ in range(int(30 / cfg.sim_dt)):
                if use_network:
                    nsim.step()
                else:
                    sim.step()
            if use_network:
                draw_network(surface, nsim, vp)
                draw_network_panel(surface, nsim, fonts, panel_x,
                                   nsim.strategy, coordinated, args.demand, speed)
            else:
                draw_intersection(surface, sim, vp)
                draw_dashboard(surface, sim, fonts, panel_x, speed)
            pygame.image.save(surface, paths[i])
        print(f"已保存 {len(paths)} 帧截图")
        pygame.quit()
        return 0

    while running:
        dt = clock.tick(FPS) / 1000.0
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    paused = not paused
                elif event.key == pygame.K_s:
                    strategy_index = (strategy_index + 1) % len(STRATEGIES)
                    rebuild(strategy=list(STRATEGIES)[strategy_index])
                elif event.key == pygame.K_d:
                    demand_index = (demand_index + 1) % len(DEMANDS)
                    rebuild(demand=DEMANDS[demand_index])
                elif event.key == pygame.K_c and use_network:
                    coordinated = not coordinated
                    rebuild()
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS, pygame.K_KP_PLUS):
                    speed_index = min(len(SPEEDS) - 1, speed_index + 1)
                    speed = float(SPEEDS[speed_index])
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    speed_index = max(0, speed_index - 1)
                    speed = float(SPEEDS[speed_index])
                elif event.key == pygame.K_r:
                    rebuild()

        if not paused:
            # 倍速：累加器按倍率放大，从而每帧执行更多仿真步
            accumulator += dt * speed
            steps = 0
            while accumulator >= cfg.sim_dt and steps < MAX_STEPS_PER_FRAME:
                if use_network:
                    nsim.step()
                else:
                    sim.step()
                accumulator -= cfg.sim_dt
                steps += 1
            # 触顶说明本帧算不完，丢弃积压，保持界面响应
            if steps >= MAX_STEPS_PER_FRAME:
                accumulator = 0.0
        else:
            accumulator = 0.0

        # 每 0.5 秒实测一次真实倍速
        now_real = time.perf_counter()
        if now_real - _real_mark >= 0.5:
            cur_t = nsim.t if use_network else sim.t
            actual_speed = (cur_t - _sim_mark) / max(1e-6, now_real - _real_mark)
            _real_mark, _sim_mark = now_real, cur_t

        if use_network:
            draw_network(surface, nsim, vp)
            draw_network_panel(surface, nsim, fonts, panel_x,
                               nsim.strategy, coordinated, nsim.cfg.demand_vph,
                               speed, actual_speed)
        else:
            draw_intersection(surface, sim, vp)
            draw_dashboard(surface, sim, fonts, panel_x, speed)
        pygame.display.flip()

    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
