"""单文件 HTML 报告生成器。

生成一个自包含的 HTML（无需任何服务器依赖，浏览器直接打开），包含：
1. 多路口网格的 Canvas 实时动画（车辆、信号灯、排队）；
2. 指标面板（各路口相位、总排队、吞吐、平均等待、绿波相位差）；
3. 实验对比表（独立配时 vs 绿波协调，含改善百分比）；
4. 内嵌图表（matplotlib 生成的对比图转 base64 内嵌）。

用法：
    python -m apps.html_report                # 默认 3x3 网格，早高峰东行偏置
    python -m apps.html_report --grid 2x3     # 自定义网格
    python -m apps.html_report --lite         # 快速短仿真
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from config import SimConfig, project_path
from engine_network import NetworkSimulation

# 复用 charts 的中文字体配置
try:
    import charts  # noqa: F401  导入即完成字体设置
except Exception:
    pass

import matplotlib.pyplot as plt

STRATEGY_LABELS = {"fixed": "固定配时", "actuated": "自适应配时", "webster": "Webster 优化", "coordinated": "绿波协调"}
STRATEGY_COLORS = {"fixed": "#818CF8", "actuated": "#2DD4BF", "webster": "#FACC15", "coordinated": "#F472B6"}
APPROACH_TRAVEL = {0: (1, 0), 1: (0, -1), 2: (-1, 0), 3: (0, 1)}


def _img_to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=120, facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def run_comparison(rows, cols, link_length, quick) -> dict:
    """跑「独立配时 vs 绿波协调」并返回结果 + 内嵌图表 + 动画帧。"""
    warmup = 60 if quick else 180
    measure = 120 if quick else 360
    demand = 700

    results = {}
    series = {}
    frames = {}
    for label, coord in (("独立配时", False), ("绿波协调", True)):
        cfg = SimConfig(demand_vph=demand, warmup_seconds=warmup, measure_seconds=measure, seed=7)
        sim = NetworkSimulation(cfg, rows=rows, cols=cols, link_length=link_length,
                                strategy='fixed', coordinated=coord,
                                direction_bias=3, bias_factor=3.0)
        r = sim.run()
        results[label] = r
        series[label] = r["series"]
        # 捕获动画帧（统计期后半段每 2 秒一帧）
        if coord:
            cap_times = [warmup + measure * 0.6 + k * 2 for k in range(60)]
            flist = []
            for t in cap_times:
                if t > cfg.total_seconds:
                    break
                st = sim.capture_state(t)
                flist.append(st)
            frames = flist
    return {"rows": rows, "cols": cols, "link_length": link_length,
            "results": results, "series": series, "frames": frames}


def build_html(comparison: dict) -> str:
    """根据对比结果生成单文件 HTML。"""
    rows = comparison["rows"]
    cols = comparison["cols"]
    results = comparison["results"]
    series = comparison["series"]

    base = results["独立配时"]
    coord = results["绿波协调"]
    d_wait = (coord["mean_wait"] - base["mean_wait"]) / base["mean_wait"] * 100
    d_queue = (coord["max_queue"] - base["max_queue"]) / max(base["max_queue"], 1) * 100
    d_wait_cls = "win" if d_wait < 0 else "lose"
    d_queue_cls = "win" if d_queue < 0 else "lose"

    # 内嵌对比图
    fig, ax = plt.subplots(figsize=(6.5, 3.0), dpi=110)
    labels = list(results)
    waits = [results[k]["mean_wait"] for k in labels]
    bars = ax.bar(labels, waits, color=[STRATEGY_COLORS["fixed"], STRATEGY_COLORS["coordinated"]], width=0.5)
    for b, v in zip(bars, waits):
        ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.2f}s", ha="center", va="bottom", fontsize=10)
    ax.set_title(f"{rows}×{cols} 网格 · 早高峰东行偏置 · 平均等待对比", fontsize=12)
    ax.set_ylabel("平均等待 (秒/辆)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    chart_b64 = _img_to_base64(fig)

    # 网格几何与动画帧
    link = comparison["link_length"]
    rows_json = json.dumps(rows)
    cols_json = json.dumps(cols)
    link_json = json.dumps(link)
    series_json = json.dumps(series)
    frames_json = json.dumps(comparison["frames"])

    html = _HTML_TEMPLATE.format(
        rows=rows, cols=cols,
        d_wait=d_wait, d_queue=d_queue,
        d_wait_cls=d_wait_cls, d_queue_cls=d_queue_cls,
        base_wait=base["mean_wait"], coord_wait=coord["mean_wait"],
        base_queue=base["max_queue"], coord_queue=coord["max_queue"],
        base_thr=base["throughput_vph"], coord_thr=coord["throughput_vph"],
        chart_b64=chart_b64,
        rows_json=rows_json, cols_json=cols_json, link_json=link_json,
        series_json=series_json, frames_json=frames_json,
    )
    return html


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>多路口网格交通信号仿真报告</title>
<style>
  :root {{ --bg:#0a0e1a; --panel:#101828; --border:#263449; --text:#e2e8f0; --dim:#8c98ac; --accent:#2dd4bf; --coord:#f472b6; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font-family:"Microsoft YaHei",system-ui,sans-serif; }}
  header {{ padding:18px 24px; background:var(--panel); border-bottom:2px solid var(--border); }}
  h1 {{ margin:0 0 6px; font-size:20px; color:var(--accent); }}
  .sub {{ color:var(--dim); font-size:13px; }}
  .wrap {{ display:flex; gap:16px; padding:16px 24px; }}
  .left {{ flex:1; min-width:0; }}
  .right {{ width:400px; }}
  canvas {{ background:#151b28; border-radius:8px; display:block; }}
  .card {{ background:var(--panel); border-radius:8px; border:1px solid var(--border); padding:14px 16px; margin-bottom:16px; }}
  .card h2 {{ margin:0 0 10px; font-size:15px; color:var(--accent); }}
  .metric {{ display:flex; justify-content:space-between; padding:5px 0; border-bottom:1px solid var(--border); font-size:14px; }}
  .metric b {{ font-variant-numeric:tabular-nums; }}
  .win {{ color:#34d399; }} .lose {{ color:#f87171; }}
  .kpi {{ display:flex; gap:12px; margin-bottom:12px; }}
  .kpi .box {{ flex:1; background:#0d1524; border:1px solid var(--border); border-radius:8px; padding:10px; text-align:center; }}
  .kpi .num {{ font-size:22px; font-weight:700; }}
  .kpi .lbl {{ color:var(--dim); font-size:12px; margin-top:2px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th, td {{ padding:7px 8px; text-align:left; border-bottom:1px solid var(--border); }}
  th {{ color:var(--dim); font-weight:500; }}
  img {{ width:100%; border-radius:6px; }}
  .legend {{ display:flex; gap:14px; font-size:12px; margin:8px 0; }}
  .legend span {{ display:inline-flex; align-items:center; gap:5px; }}
  .dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
</style>
</head>
<body>
<header>
  <h1>多路口网格交通信号仿真报告</h1>
  <div class="sub">网格 {rows}×{cols} · 早高峰东行偏置 · 独立配时 vs 绿波协调（相位差）对比</div>
</header>
<div class="wrap">
  <div class="left">
    <div class="card">
      <h2>路口车流实时动画</h2>
      <div class="legend">
        <span><i class="dot" style="background:#2dd4bf"></i>直行车</span>
        <span><i class="dot" style="background:#818cf8"></i>转向车</span>
        <span><i class="dot" style="background:#f472b6"></i>排队车</span>
        <span><i class="dot" style="background:#ef4444"></i>红灯</span>
        <span><i class="dot" style="background:#22c55e"></i>绿灯</span>
      </div>
      <canvas id="cv" width="760" height="560"></canvas>
    </div>
    <div class="card">
      <h2>平均等待时间对比</h2>
      <img src="data:image/png;base64,{chart_b64}" alt="平均等待对比">
    </div>
  </div>
  <div class="right">
    <div class="card">
      <h2>关键指标</h2>
      <div class="kpi">
        <div class="box"><div class="num" id="kWait" style="color:var(--coord)">{coord_wait}s</div><div class="lbl">协调·平均等待</div></div>
        <div class="box"><div class="num" id="kQueue">{coord_queue}</div><div class="lbl">协调·最大排队</div></div>
        <div class="box"><div class="num">{coord_thr}</div><div class="lbl">协调·吞吐量/h</div></div>
      </div>
      <table>
        <tr><th>指标</th><th>独立配时</th><th>绿波协调</th><th>改善</th></tr>
        <tr><td>平均等待</td><td>{base_wait}s</td><td>{coord_wait}s</td>
          <td class="{d_wait_cls}">{d_wait:+.1f}%</td></tr>
        <tr><td>最大排队</td><td>{base_queue}</td><td>{coord_queue}</td>
          <td class="{d_queue_cls}">{d_queue:+.1f}%</td></tr>
        <tr><td>吞吐量</td><td>{base_thr}/h</td><td>{coord_thr}/h</td><td>—</td></tr>
      </table>
    </div>
    <div class="card">
      <h2>绿波协调原理</h2>
      <p style="font-size:13px;line-height:1.7;color:var(--text);">
      相邻路口共享同一<strong>公共周期</strong>，按「路段长度 ÷ 期望车速」计算
      <strong>相位差</strong>，使绿灯沿主干道方向依次错开——车辆以绿波车速行驶时
      可一路连续通过多个路口，减少停车与启停延误。
      </p>
      <p style="font-size:12px;color:var(--dim);">
      本实验采用西→东主干道偏置（西进口需求放大 3 倍），绿波沿东行方向推进。
      </p>
    </div>
  </div>
</div>
<script>
const rows = {rows_json}, cols = {cols_json}, LINK = {link_json};
const frames = {frames_json};
const canvas = document.getElementById('cv'), ctx = canvas.getContext('2d');
const W = canvas.width, H = canvas.height;
const S = W / Math.max(cols * LINK * 1.35, 1);
const cx = W/2, cy = H/2;
function wp(i,j,s,dir){{
  const dx0 = (j - (cols-1)/2) * LINK;
  const dz0 = (i - (rows-1)/2) * LINK;
  const dv = {{0:[0,1],1:[-1,0],2:[0,-1],3:[1,0]}}[dir];
  return [cx + (dx0 + dv[0]*s)*S, cy + (dz0 + dv[1]*s)*S];
}}
function draw(frame){{
  if(!frame) return;
  ctx.fillStyle='#151b28'; ctx.fillRect(0,0,W,H);
  // 路段
  ctx.strokeStyle='#2a3348'; ctx.lineWidth=8; ctx.lineCap='round';
  for(let i=0;i<rows;i++) for(let j=0;j<cols;j++){{
    for(const d of [1,3]){{ let a=wp(i,j,0,d), b=wp(i,j,LINK*1.1,d);
      ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(b[0],b[1]); ctx.stroke(); }}
    for(const d of [0,2]){{ let a=wp(i,j,0,d), b=wp(i,j,LINK*1.1,d);
      ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(b[0],b[1]); ctx.stroke(); }}
  }}
  // 路口 + 信号灯
  const sig = frame.signals || {{}};
  for(let i=0;i<rows;i++) for(let j=0;j<cols;j++){{
    const p=wp(i,j,0,0);
    const st = sig[i+','+j];
    const green = st === 'green';
    ctx.fillStyle='#0d1524'; ctx.beginPath(); ctx.arc(p[0],p[1],14,0,7); ctx.fill();
    ctx.fillStyle = green ? '#22c55e' : (st==='yellow'?'#eab308':'#ef4444');
    ctx.beginPath(); ctx.arc(p[0],p[1],8,0,7); ctx.fill();
  }}
  // 车辆
  for(const c of frame.vehicles){{
    const p=wp(c.i,c.j,c.s,c.dir);
    ctx.fillStyle = c.queued ? '#f472b6' : (c.turn==='through'?'#2dd4bf':'#818cf8');
    ctx.save(); ctx.translate(p[0],p[1]);
    const ang = (c.dir===1||c.dir===3) ? 0 : Math.PI/2;
    ctx.rotate(ang); ctx.fillRect(-6,-3,12,6); ctx.restore();
  }}
  // 时间水印
  ctx.fillStyle='#8c98ac'; ctx.font='13px sans-serif';
  ctx.fillText('t = ' + frame.t + 's · 排队 ' + frame.queue + ' 辆', 12, H-12);
}}
// 循环播放动画帧
let fi = 0;
function animate(){{
  if(frames.length){{
    draw(frames[fi]);
    fi = (fi + 1) % frames.length;
  }}
}}
draw(frames[0]);
setInterval(animate, 120);
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成多路口网格仿真 HTML 报告")
    parser.add_argument("--grid", default="3x2", help="网格尺寸，如 3x2")
    parser.add_argument("--link", type=float, default=220.0, help="路段长度（米）")
    parser.add_argument("--lite", action="store_true", help="短仿真快速生成")
    parser.add_argument("--out", default="report/report.html", help="输出HTML路径")
    args = parser.parse_args(argv)

    try:
        r, c = args.grid.split("x")
        rows, cols = int(r), int(c)
    except Exception:
        rows, cols = 3, 2

    print("正在运行网格仿真对比（独立配时 vs 绿波协调）...")
    comparison = run_comparison(rows, cols, args.link, args.lite)
    html = build_html(comparison)

    out = project_path(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)

    d_wait = (comparison["results"]["绿波协调"]["mean_wait"] - comparison["results"]["独立配时"]["mean_wait"]) \
        / comparison["results"]["独立配时"]["mean_wait"] * 100
    print(f"\n网格 {rows}×{cols} 报告已生成: {out}")
    print(f"独立配时平均等待 {comparison['results']['独立配时']['mean_wait']}s，"
          f"绿波协调 {comparison['results']['绿波协调']['mean_wait']}s（{d_wait:+.1f}%）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
