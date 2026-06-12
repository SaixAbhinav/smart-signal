// SmartSignal dashboard: renders lockstep simulations streamed over WebSocket.
// Two renderers: a hand-drawn single-intersection view, and a generic vector
// view for grid scenarios whose edge ids follow the "A__B" naming convention.

const COLORS = { fixed: "#e89aa4", actuated: "#f0bd8d", maxpressure: "#94b4e4", rl: "#8fd4ae" };
const LABELS = { fixed: "Fixed timer", actuated: "Actuated (SUMO)", maxpressure: "Max-pressure", rl: "PPO agent (RL)" };
const SIGNAL = { green: "#34b27d", yellow: "#e6ac2f", red: "#e06c66" };
const INK = "#38324a", INK_SOFT = "#7b748f", GRID_LINE = "#ece9f4";
const ROAD = "#e7e4f0", JUNCTION = "#dcd7ea", LANE_LINE = "#d2cce2", QUEUE = "rgba(224, 108, 102, 0.75)";

// --- single intersection geometry (320x320 canvas, right-hand traffic) -------
const C = 160, HALF = 42, LW = 14, BOX = [C - HALF, C + HALF];
function laneRect(dir, idx) {
  switch (dir) {
    case "N": return { x: 118 + idx * LW, y: 0, w: LW, h: 118, vert: true, stop: 118, dq: -1 };
    case "S": return { x: 188 - idx * LW, y: 202, w: LW, h: 118, vert: true, stop: 202, dq: 1 };
    case "E": return { x: 202, y: 118 + idx * LW, w: 118, h: LW, vert: false, stop: 202, dq: 1 };
    case "W": return { x: 0, y: 188 - idx * LW, w: 118, h: LW, vert: false, stop: 118, dq: -1 };
  }
}

function drawIntersection(ctx, lanes, colors, queues) {
  ctx.clearRect(0, 0, 320, 320);
  ctx.fillStyle = ROAD;
  ctx.fillRect(BOX[0], 0, HALF * 2, 320);
  ctx.fillRect(0, BOX[0], 320, HALF * 2);
  ctx.fillStyle = JUNCTION;
  ctx.fillRect(BOX[0], BOX[0], HALF * 2, HALF * 2);
  ctx.strokeStyle = LANE_LINE;
  ctx.beginPath();
  ctx.moveTo(C, 0); ctx.lineTo(C, BOX[0]); ctx.moveTo(C, BOX[1]); ctx.lineTo(C, 320);
  ctx.moveTo(0, C); ctx.lineTo(BOX[0], C); ctx.moveTo(BOX[1], C); ctx.lineTo(320, C);
  ctx.stroke();

  for (const lane of lanes) {
    const [dir, , idxStr] = lane.split("_");
    const idx = +idxStr;
    const r = laneRect(dir, idx);
    ctx.strokeStyle = LANE_LINE;
    ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1);
    const q = Math.min(queues[lane] || 0, 22);
    if (q > 0) {
      ctx.fillStyle = QUEUE;
      const len = q * 5;
      if (r.vert) ctx.fillRect(r.x + 2, r.dq < 0 ? r.stop - len : r.stop, r.w - 4, len);
      else ctx.fillRect(r.dq < 0 ? r.stop - len : r.stop, r.y + 2, len, r.h - 4);
    }
    ctx.fillStyle = SIGNAL[colors[lane]] || INK_SOFT;
    if (r.vert) ctx.fillRect(r.x + 2, r.dq < 0 ? r.stop - 5 : r.stop + 1, r.w - 4, 4);
    else ctx.fillRect(r.dq < 0 ? r.stop - 5 : r.stop + 1, r.y + 2, 4, r.h - 4);
  }
  ctx.fillStyle = INK_SOFT;
  ctx.font = "11px Outfit, sans-serif";
  ctx.fillText("N", 154, 12); ctx.fillText("S", 154, 314);
  ctx.fillText("W", 6, 164); ctx.fillText("E", 306, 164);
}

// --- generic grid renderer ----------------------------------------------------
// Lane ids look like "W00__J00_2": edge from node W00 to node J00, lane 2.
// Lane 0 is the rightmost lane (right-hand traffic).
function buildGridGeometry(lanes, nodes, W = 320, H = 320, pad = 20) {
  const xs = Object.values(nodes).map(p => p[0]);
  const ys = Object.values(nodes).map(p => p[1]);
  const [minX, maxX] = [Math.min(...xs), Math.max(...xs)];
  const [minY, maxY] = [Math.min(...ys), Math.max(...ys)];
  const s = Math.min((W - 2 * pad) / (maxX - minX), (H - 2 * pad) / (maxY - minY));
  const tx = x => pad + (x - minX) * s;
  const ty = y => H - (pad + (y - minY) * s);

  const lw = 3.5, jr = 13, nLanes = 3;
  const geo = { lanes: {}, segs: [], junctions: [] };
  const segSeen = new Set();
  const junctionSeen = new Set();

  for (const lane of lanes) {
    const m = lane.match(/^(.+)__(.+)_(\d+)$/);
    if (!m || !nodes[m[1]] || !nodes[m[2]]) return null;
    const [, a, b, idxStr] = m;
    const idx = +idxStr;
    const p1 = [tx(nodes[a][0]), ty(nodes[a][1])];
    const p2 = [tx(nodes[b][0]), ty(nodes[b][1])];
    const len = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
    const d = [(p2[0] - p1[0]) / len, (p2[1] - p1[1]) / len];
    const r = [-d[1], d[0]]; // right-hand side of travel, canvas coords
    const off = lw * (nLanes - idx - 0.5);
    const stop = [
      p2[0] - d[0] * jr + r[0] * off,
      p2[1] - d[1] * jr + r[1] * off,
    ];
    geo.lanes[lane] = { stop, back: [-d[0], -d[1]], maxLen: len - 2 * jr };

    const segKey = [a, b].sort().join("|");
    if (!segSeen.has(segKey)) {
      segSeen.add(segKey);
      geo.segs.push([p1, p2]);
    }
    if (b.startsWith("J") && !junctionSeen.has(b)) {
      junctionSeen.add(b);
      geo.junctions.push({ id: b, p: p2 });
    }
  }
  geo.roadWidth = lw * nLanes * 2 + 2;
  geo.lw = lw;
  return geo;
}

function drawGrid(ctx, geo, colors, queues) {
  ctx.clearRect(0, 0, 320, 320);
  ctx.strokeStyle = ROAD;
  ctx.lineWidth = geo.roadWidth;
  for (const [p1, p2] of geo.segs) {
    ctx.beginPath(); ctx.moveTo(p1[0], p1[1]); ctx.lineTo(p2[0], p2[1]); ctx.stroke();
  }
  ctx.fillStyle = JUNCTION;
  for (const j of geo.junctions) {
    const r = geo.roadWidth / 2 + 1;
    ctx.fillRect(j.p[0] - r, j.p[1] - r, 2 * r, 2 * r);
  }
  for (const [lane, g] of Object.entries(geo.lanes)) {
    const q = Math.min(queues[lane] || 0, 25);
    if (q > 0) {
      const len = Math.min(q * 3, g.maxLen);
      ctx.strokeStyle = QUEUE;
      ctx.lineWidth = geo.lw - 1;
      ctx.beginPath();
      ctx.moveTo(g.stop[0], g.stop[1]);
      ctx.lineTo(g.stop[0] + g.back[0] * len, g.stop[1] + g.back[1] * len);
      ctx.stroke();
    }
    ctx.fillStyle = SIGNAL[colors[lane]] || INK_SOFT;
    ctx.beginPath();
    ctx.arc(g.stop[0], g.stop[1], 2.2, 0, 2 * Math.PI);
    ctx.fill();
  }
  ctx.fillStyle = INK_SOFT;
  ctx.font = "10px Outfit, sans-serif";
  for (const j of geo.junctions) ctx.fillText(j.id, j.p[0] - 9, j.p[1] + 3);
}

// --- app state ---------------------------------------------------------------
let ws = null, chart = null, panels = {}, lanes = [], gridGeo = null, cfg = null;

async function init() {
  cfg = await (await fetch("/api/config")).json();
  const scenarioSel = document.getElementById("scenario");
  for (const s of Object.keys(cfg.scenarios)) scenarioSel.add(new Option(s, s));
  scenarioSel.onchange = applyScenario;
  applyScenario();
}

function applyScenario() {
  const scen = cfg.scenarios[document.getElementById("scenario").value];
  const profileSel = document.getElementById("profile");
  profileSel.innerHTML = "";
  scen.profiles.forEach(p => profileSel.add(new Option(p, p)));
  const ctrls = document.getElementById("ctrls");
  ctrls.innerHTML = "";
  for (const c of scen.controllers) {
    const checked = (c === "fixed" || c === "rl" || (c === "actuated" && !scen.rl_available)) ? "checked" : "";
    ctrls.insertAdjacentHTML("beforeend",
      `<label><input type="checkbox" value="${c}" ${checked}> ${LABELS[c]}</label>`);
  }
  if (!scen.rl_available) {
    ctrls.insertAdjacentHTML("beforeend",
      `<label style="color:var(--ink-soft)">(train a model to enable RL)</label>`);
  }
}

function highlightChartLine(name) {
  if (!chart) return;
  chart.data.datasets.forEach(ds => {
    const dsName = Object.keys(LABELS).find(k => LABELS[k] === ds.label);
    ds.borderWidth = name === null ? 2.5 : (dsName === name ? 4 : 1.5);
  });
  chart.update("none");
}

function buildPanels(names) {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  panels = {};
  for (const name of names) {
    const div = document.createElement("div");
    div.className = "sim-panel";
    div.innerHTML = `
      <h3><span class="dot" style="background:${COLORS[name]}"></span>${LABELS[name]}</h3>
      <canvas width="320" height="320"></canvas>
      <div class="stats">
        <span>queued<b class="q">0</b></span>
        <span>throughput<b class="a">0</b></span>
        <span>total wait<b class="w">0</b></span>
      </div>`;
    div.onmouseenter = () => highlightChartLine(name);
    div.onmouseleave = () => highlightChartLine(null);
    grid.appendChild(div);
    panels[name] = {
      ctx: div.querySelector("canvas").getContext("2d"),
      q: div.querySelector(".q"), a: div.querySelector(".a"), w: div.querySelector(".w"),
    };
  }

  const board = document.getElementById("board");
  board.innerHTML = "";
  for (const name of names) {
    board.insertAdjacentHTML("beforeend", `
      <div class="board-chip" data-name="${name}">
        <span class="swatch" style="background:${COLORS[name]}"></span>
        <b>${LABELS[name]}</b>
        <span class="val mono">0 veh·min</span>
        <span class="tag" hidden>least waiting</span>
      </div>`);
  }

  if (chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: {
      labels: [],
      datasets: names.map(n => ({
        label: LABELS[n], data: [], borderColor: COLORS[n],
        pointRadius: 0, borderWidth: 2.5, tension: 0.3,
      })),
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: "simulation time (s)", color: INK_SOFT }, ticks: { color: INK_SOFT, maxTicksLimit: 12 }, grid: { color: GRID_LINE } },
        y: { title: { display: true, text: "cumulative waiting (vehicle-seconds)", color: INK_SOFT }, ticks: { color: INK_SOFT }, grid: { color: GRID_LINE } },
      },
      plugins: { legend: { labels: { color: INK, font: { family: "Outfit" } } } },
    },
  });
}

function updateBoard(sims) {
  const board = document.getElementById("board");
  const ranked = Object.entries(sims)
    .map(([name, s]) => ({ name, wait: s.metrics.cum_wait }))
    .sort((a, b) => a.wait - b.wait);
  ranked.forEach((r, i) => {
    const chip = board.querySelector(`[data-name="${r.name}"]`);
    if (!chip) return;
    chip.style.order = i;
    chip.classList.toggle("leader", i === 0 && ranked.length > 1);
    chip.querySelector(".tag").hidden = !(i === 0 && ranked.length > 1);
    chip.querySelector(".val").textContent = (r.wait / 60).toFixed(0) + " veh·min";
  });
}

function start() {
  const names = [...document.querySelectorAll("#ctrls input:checked")].map(i => i.value);
  if (!names.length) return alert("pick at least one controller");
  buildPanels(names);
  ws = new WebSocket(`ws://${location.host}/ws`);
  ws.onopen = () => {
    ws.send(JSON.stringify({
      cmd: "start",
      scenario: document.getElementById("scenario").value,
      profile: document.getElementById("profile").value,
      seed: +document.getElementById("seed").value,
      controllers: names,
      speed: +document.getElementById("speed").value,
    }));
    setStatus("running", true);
  };
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === "init") {
      lanes = msg.lanes;
      gridGeo = msg.scenario === "single" ? null : buildGridGeometry(lanes, msg.nodes);
    } else if (msg.type === "frame") onFrame(msg);
    else if (msg.type === "done") setStatus("episode finished", false);
  };
  ws.onclose = () => { if (!document.getElementById("start").disabled) return; setStatus("idle", false); };
}

function onFrame(msg) {
  document.getElementById("status").textContent = `t = ${msg.time}s`;
  for (const [name, sim] of Object.entries(msg.sims)) {
    const p = panels[name];
    if (!p) continue;
    if (gridGeo) drawGrid(p.ctx, gridGeo, sim.colors, sim.queues);
    else drawIntersection(p.ctx, lanes, sim.colors, sim.queues);
    p.q.textContent = sim.metrics.queued;
    p.a.textContent = sim.metrics.arrived;
    p.w.textContent = (sim.metrics.cum_wait / 60).toFixed(0) + " veh·min";
  }
  updateBoard(msg.sims);
  if (msg.time % 10 === 0 && chart) {
    chart.data.labels.push(msg.time);
    chart.data.datasets.forEach(ds => {
      const name = Object.keys(LABELS).find(k => LABELS[k] === ds.label);
      ds.data.push(msg.sims[name]?.metrics.cum_wait ?? null);
    });
    chart.update("none");
  }
}

function setStatus(text, running) {
  const el = document.getElementById("status");
  el.textContent = text;
  el.classList.toggle("live", running);
  document.getElementById("start").disabled = running;
  document.getElementById("stop").disabled = !running;
}

document.getElementById("start").onclick = start;
document.getElementById("stop").onclick = () => {
  ws?.send(JSON.stringify({ cmd: "stop" }));
  ws?.close();
  setStatus("stopped", false);
};
document.getElementById("speed").oninput = e => {
  document.getElementById("speedVal").textContent = e.target.value + "×";
  ws?.send(JSON.stringify({ cmd: "speed", value: +e.target.value }));
};

init();
