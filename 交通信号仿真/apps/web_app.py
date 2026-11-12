"""Web 控制面板（Flask）。

    python main.py --web            # 启动后浏览器打开 http://127.0.0.1:8050

提供：
* /            —— 单页控制台：实时渲染路口（Canvas）、切换策略、调车流、启停；
* /api/state   —— 仿真实时状态（车辆坐标、信号灯、指标）；
* /api/control —— POST 控制（切换策略 / 重置 / 设置车流）；
* /api/history —— 历史仿真记录（来自数据库）。

Web 面板在无桌面环境（服务器 / CI）也能展示仿真，与 Pygame 桌面端互补。
"""

from __future__ import annotations

import argparse
import json
import threading

from flask import Flask, jsonify, request

from config import SimConfig
from engine import Simulation
from controllers.strategies import STRATEGIES, create_controller

app = Flask(__name__)

STATE = {
    "sim": None,
    "lock": threading.Lock(),
    "running": True,
    "speed": 1.0,          # 每帧推进的仿真秒数
    "strategy": "actuated",
    "demand": 600.0,
    "demand_ratio": 1.0,
}


def _new_sim() -> Simulation:
    cfg = SimConfig(demand_vph=STATE["demand"], demand_ratio_ew=STATE["demand_ratio"],
                    warmup_seconds=120, measure_seconds=600)
    return Simulation(cfg, STATE["strategy"])


def _step_sim() -> None:
    with STATE["lock"]:
        if STATE["running"] and STATE["sim"] is not None:
            for _ in range(int(STATE["speed"] * 5)):
                STATE["sim"].step()


@app.route("/")
def index():
    return _HTML


@app.route("/api/state")
def api_state():
    with STATE["lock"]:
        sim = STATE["sim"]
        if sim is None:
            return jsonify({"ready": False})
        q = sim.queue_by_phase()
        vehicles = []
        for v in sim.vehicles:
            x, z = v.position
            vehicles.append({
                "x": round(x, 1), "z": round(z, 1),
                "move": v.lane.move, "dir": v.lane.direction,
                "queued": v.queued,
            })
        waits = [d["wait"] for d in sim.departed]
        return jsonify({
            "ready": True,
            "t": round(sim.t, 1),
            "measuring": sim.measuring,
            "strategy": sim.strategy,
            "phase": sim.controller.phase,
            "phase_name": sim.controller.phase_name,
            "state": sim.controller.state,
            "green_elapsed": round(sim.controller.green_elapsed, 1),
            "green_planned": round(sim.controller.green_planned, 1),
            "queue_ns": q[0],
            "queue_ew": q[1],
            "vehicles": vehicles,
            "count": len(vehicles),
            "throughput": round(sim.throughput_window(), 1),
            "mean_wait": round(sum(waits) / len(waits), 2) if waits else 0.0,
            "road_length": sim.cfg.road_length,
            "road_half_width": sim.cfg.road_half_width,
            "stop_line_offset": sim.cfg.stop_line_offset,
        })


@app.route("/api/control", methods=["POST"])
def api_control():
    data = request.get_json(force=True) or {}
    action = data.get("action")
    with STATE["lock"]:
        if action == "reset":
            STATE["sim"] = _new_sim()
        elif action == "strategy":
            STATE["strategy"] = data.get("strategy", "actuated")
            STATE["sim"] = _new_sim()
        elif action == "demand":
            STATE["demand"] = float(data.get("demand", 600))
            STATE["sim"] = _new_sim()
        elif action == "ratio":
            STATE["demand_ratio"] = float(data.get("ratio", 1.0))
            STATE["sim"] = _new_sim()
        elif action == "toggle":
            STATE["running"] = not STATE["running"]
        elif action == "speed":
            STATE["speed"] = float(data.get("speed", 1.0))
    return jsonify({"ok": True, "running": STATE["running"], "strategy": STATE["strategy"],
                    "demand": STATE["demand"]})


@app.route("/api/history")
def api_history():
    from storage import StrategyRepository

    try:
        repo = StrategyRepository()
        rows = repo.list_runs(limit=100)
        repo.close()
        return jsonify({"ok": True, "rows": rows})
    except Exception as e:  # noqa: BLE001
        return jsonify({"ok": False, "error": str(e)})


_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>交通信号配时仿真</title>
<style>
  :root { --bg:#0a0e1a; --panel:#101828; --border:#263449; --text:#e2e8f0; --dim:#8c98ac; --accent:#2dd4bf; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--text); font-family:"Microsoft YaHei",system-ui,sans-serif; }
  .wrap { display:flex; height:100vh; }
  canvas { background:#151b28; }
  .side { width:300px; background:var(--panel); padding:16px; border-left:2px solid var(--border); overflow:auto; }
  h1 { font-size:18px; color:var(--accent); margin:0 0 12px; }
  .row { margin:8px 0; }
  .label { color:var(--dim); font-size:12px; }
  .val { font-size:16px; }
  button { background:#1d2b42; color:var(--text); border:1px solid var(--border); border-radius:6px; padding:8px 12px; margin:4px 4px 4px 0; cursor:pointer; font-size:13px; }
  button.on { background:var(--accent); color:#06251f; border-color:var(--accent); }
  .metric { display:flex; justify-content:space-between; padding:4px 0; border-bottom:1px solid var(--border); }
  .badge { display:inline-block; padding:2px 8px; border-radius:10px; font-size:12px; }
  .g { background:#22c55e; color:#052e16; } .y { background:#eab308; color:#422006; } .r { background:#ef4444; color:#450a0a; }
</style>
</head>
<body>
<div class="wrap">
  <canvas id="cv" width="1100" height="900"></canvas>
  <div class="side">
    <h1>交通信号配时仿真</h1>
    <div class="row"><span class="label">策略</span><br><span class="val" id="strategy">-</span></div>
    <div class="row"><span class="label">相位 / 信号</span><br><span class="val"><span id="phase">-</span> <span id="state" class="badge">-</span></span></div>
    <div class="row"><span class="label">绿灯已用 / 计划</span><br><span class="val" id="green">-</span></div>
    <div class="row"><span class="label">仿真时间</span><br><span class="val" id="time">-</span></div>
    <hr>
    <div class="metric"><span>南北排队</span><b id="qns">0</b></div>
    <div class="metric"><span>东西排队</span><b id="qew">0</b></div>
    <div class="metric"><span>在场车辆</span><b id="cnt">0</b></div>
    <div class="metric"><span>滚动吞吐量</span><b id="thr">0 辆/时</b></div>
    <div class="metric"><span>平均等待</span><b id="wait">0 s</b></div>
    <hr>
    <div class="row">
      <button id="btnPause" onclick="ctl('toggle')">暂停</button>
      <button onclick="ctl('reset')">重置</button>
    </div>
    <div class="row"><span class="label">切换策略</span><br>
      <button id="bFixed" onclick="ctl('strategy','fixed')">固定配时</button>
      <button id="bAct" class="on" onclick="ctl('strategy','actuated')">自适应</button>
      <button id="bWeb" onclick="ctl('strategy','webster')">Webster</button>
    </div>
    <div class="row"><span class="label">车流量（辆/时/进口道）</span><br>
      <button onclick="ctl('demand',300)">300</button>
      <button class="on" onclick="ctl('demand',600)">600</button>
      <button onclick="ctl('demand',900)">900</button>
      <button onclick="ctl('demand',1200)">1200</button>
    </div>
  </div>
</div>
<script>
const cv = document.getElementById('cv'), ctx = cv.getContext('2d');
const S = 3.2, cx = 550, cy = 450;
function wp(x,z){ return [cx + x*S, cy + z*S]; }
async function ctl(action, v){ await fetch('/api/control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:action,strategy:v,demand:v})}); if(action==='strategy'||action==='demand'){ [['bFixed','fixed'],['bAct','actuated'],['bWeb','webster']].forEach(([id,val])=>document.getElementById(id).classList.toggle('on',val===v)); } }
async function tick(){
  try{
    const r = await (await fetch('/api/state')).json();
    if(!r.ready) return;
    // 画布
    ctx.fillStyle = '#151b28'; ctx.fillRect(0,0,cv.width,cv.height);
    const hw=r.road_half_width, rl=r.road_length;
    // 道路
    ctx.fillStyle='#212733';
    let p=wp(-hw,-rl), q=wp(hw,rl); ctx.fillRect(p[0],p[1],q[0]-p[0],q[1]-p[1]);
    p=wp(-rl,-hw); q=wp(rl,hw); ctx.fillRect(p[0],p[1],q[0]-p[0],q[1]-p[1]);
    // 车道线
    ctx.strokeStyle='#d6dbe4'; ctx.lineWidth=2; ctx.setLineDash([10,8]);
    for(const off of [-hw/3,hw/3]){
      ctx.beginPath(); let a=wp(off,-rl); ctx.moveTo(a[0],a[1]); let b=wp(off,rl); ctx.lineTo(b[0],b[1]); ctx.stroke();
      ctx.beginPath(); a=wp(-rl,off); ctx.moveTo(a[0],a[1]); b=wp(rl,off); ctx.lineTo(b[0],b[1]); ctx.stroke();
    }
    ctx.setLineDash([]);
    // 停车线
    const so=r.stop_line_offset, dirs={0:[0,1],1:[-1,0],2:[0,-1],3:[1,0]};
    ctx.strokeStyle='#ebeef4'; ctx.lineWidth=3;
    for(let d=0;d<4;d++){ const f=dirs[d], nx=f[1], nz=-f[0];
      let a=wp(-f[0]*so+nx*hw, -f[1]*so+nz*hw), b=wp(-f[0]*so-nx*hw, -f[1]*so-nz*hw);
      ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(b[0],b[1]); ctx.stroke(); }
    // 信号灯
    for(let d=0;d<4;d++){ const f=dirs[d], nx=f[1], nz=-f[0];
      const on = (d%2===r.phase) && (r.state==='green'||r.state==='yellow');
      const col = r.state==='green'?'#22c55e':r.state==='yellow'?'#eab308':'#ef4444';
      let a=wp(-f[0]*(so+2)+nx*(hw+4), -f[1]*(so+2)+nz*(hw+4));
      ctx.fillStyle='#141824'; ctx.beginPath(); ctx.arc(a[0],a[1],9,0,7); ctx.fill();
      ctx.fillStyle = on?col:'#ef4444'; ctx.beginPath(); ctx.arc(a[0],a[1],6,0,7); ctx.fill(); }
    // 车辆
    const col={through:'#2dd4bf',left:'#818cf8',right:'#facc15'};
    for(const v of r.vehicles){ let a=wp(v.x,v.z); ctx.fillStyle=v.queued?'#f472b6':col[v.move];
      ctx.save(); ctx.translate(a[0],a[1]); ctx.fillRect(-7,-3.5,14,7); ctx.restore(); }
    // 面板
    document.getElementById('strategy').textContent = r.strategy;
    document.getElementById('phase').textContent = r.phase_name;
    document.getElementById('state').textContent = r.state.toUpperCase();
    document.getElementById('state').className = 'badge '+(r.state==='green'?'g':r.state==='yellow'?'y':'r');
    document.getElementById('green').textContent = r.green_elapsed+'s / '+r.green_planned+'s';
    document.getElementById('time').textContent = r.t+'s '+(r.measuring?'(统计期)':'(预热期)');
    document.getElementById('qns').textContent = r.queue_ns;
    document.getElementById('qew').textContent = r.queue_ew;
    document.getElementById('cnt').textContent = r.count;
    document.getElementById('thr').textContent = r.throughput+' 辆/时';
    document.getElementById('wait').textContent = r.mean_wait+' s';
  }catch(e){}
  setTimeout(tick, 150);
}
tick();
</script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Web 控制面板")
    parser.add_argument("--port", type=int, default=8050)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)

    STATE["sim"] = _new_sim()

    # 后台线程推进仿真（与 Web 请求解耦）
    def loop():
        import time

        while True:
            _step_sim()
            time.sleep(0.033)

    threading.Thread(target=loop, daemon=True).start()

    print(f"Web 控制面板: http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
