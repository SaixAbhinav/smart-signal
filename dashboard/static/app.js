// SmartSignal dashboard: renders lockstep simulations streamed over WebSocket.
// One geometry-driven renderer for every scenario: the server sends each lane's
// real polyline once, then a per-vehicle position list each frame. The client
// maps world -> canvas, draws the roads, the signal heads, and the cars, and
// interpolates car positions between frames so motion stays fluid at high speed.

const COLORS = { fixed: "#e89aa4", actuated: "#f0bd8d", maxpressure: "#94b4e4", rl: "#8fd4ae" };
const LABELS = { fixed: "Fixed timer", actuated: "Actuated (SUMO)", maxpressure: "Max-pressure", rl: "PPO agent (RL)" };
const SIGNAL = { green: "#34b27d", yellow: "#e6ac2f", red: "#e06c66" };
const INK_SOFT = "#7b748f", ROAD = "#e7e4f0", LANE_LINE = "#d2cce2";
const CAR_MOVING = "#5fb98a", CAR_STOPPED = "#e06c66";
const CANVAS = 320, PAD = 18;
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// --- world -> canvas transform from the network bounding box ------------------
function makeTransform(bounds) {
  const [[x0, y0], [x1, y1]] = bounds;
  const w = Math.max(x1 - x0, 1), h = Math.max(y1 - y0, 1);
  const scale = Math.min((CANVAS - 2 * PAD) / w, (CANVAS - 2 * PAD) / h);
  const ox = (CANVAS - w * scale) / 2, oy = (CANVAS - h * scale) / 2;
  return {
    scale,
    tx: x => ox + (x - x0) * scale,
    ty: y => CANVAS - (oy + (y - y0) * scale), // flip Y: SUMO is y-up
  };
}

// --- static road layer, rasterized once per geometry to its own canvas --------
function buildRoadLayer(geo, T) {
  const c = document.createElement("canvas");
  c.width = CANVAS; c.height = CANVAS;
  const ctx = c.getContext("2d");
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  ctx.strokeStyle = ROAD;
  ctx.lineWidth = Math.max(3.4 * T.scale, 4);
  for (const pts of Object.values(geo.laneShapes)) {
    if (pts.length < 2) continue;
    ctx.beginPath();
    ctx.moveTo(T.tx(pts[0][0]), T.ty(pts[0][1]));
    for (let i = 1; i < pts.length; i++) ctx.lineTo(T.tx(pts[i][0]), T.ty(pts[i][1]));
    ctx.stroke();
  }
  return c;
}

// signal head = last point of each incoming lane, plus the inbound direction
function buildSignalHeads(geo, T) {
  const heads = {};
  for (const lane of geo.signalLanes) {
    const pts = geo.laneShapes[lane];
    if (!pts || pts.length < 2) continue;
    const a = pts[pts.length - 2], b = pts[pts.length - 1];
    const ang = Math.atan2(T.ty(b[1]) - T.ty(a[1]), T.tx(b[0]) - T.tx(a[0]));
    heads[lane] = { x: T.tx(b[0]), y: T.ty(b[1]), nx: Math.cos(ang), ny: Math.sin(ang) };
  }
  return heads;
}

function drawScene(view, frame, prev, alpha) {
  const { ctx, T, road, heads } = view;
  ctx.clearRect(0, 0, CANVAS, CANVAS);
  ctx.drawImage(road, 0, 0);

  // signal heads: a short colored cap across the lane mouth
  const capLen = Math.max(2.2 * T.scale, 3.5);
  ctx.lineWidth = Math.max(3.4 * T.scale, 4);
  ctx.lineCap = "butt";
  for (const [lane, h] of Object.entries(heads)) {
    ctx.strokeStyle = SIGNAL[frame.colors[lane]] || INK_SOFT;
    ctx.beginPath();
    ctx.moveTo(h.x - h.nx * capLen, h.y - h.ny * capLen);
    ctx.lineTo(h.x, h.y);
    ctx.stroke();
  }

  // cars: interpolate position by matching id against the previous frame
  const prevById = prev ? prev._byId : null;
  const cw = Math.max(4.6 * T.scale, 3.4), ch = Math.max(2.0 * T.scale, 2.2);
  for (const v of frame.vehicles) {
    const [id, x, y, ang, stopped] = v;
    let px = x, py = y, pa = ang;
    if (prevById && alpha < 1) {
      const p = prevById[id];
      if (p) {
        px = p[1] + (x - p[1]) * alpha;
        py = p[2] + (y - p[2]) * alpha;
        pa = p[3] + angleDelta(p[3], ang) * alpha;
      }
    }
    const cx = T.tx(px), cy = T.ty(py);
    const rad = (90 - pa) * Math.PI / 180; // SUMO angle: 0=north, clockwise
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-rad);
    ctx.fillStyle = stopped ? CAR_STOPPED : CAR_MOVING;
    roundRect(ctx, -cw / 2, -ch / 2, cw, ch, Math.min(ch / 2, 1.6));
    ctx.fill();
    ctx.restore();
  }
}

function angleDelta(a, b) {
  let d = ((b - a + 540) % 360) - 180; // shortest signed turn
  return d;
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// --- app state ----------------------------------------------------------------
let ws = null, chart = null, panels = {}, cfg = null;
let geometry = null, transform = null, roadLayer = null, signalHeads = null;
let rafId = null;

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
      view: null, prev: null, cur: null, tPrev: 0, tCur: 0,
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
        x: { title: { display: true, text: "simulation time (s)", color: INK_SOFT }, ticks: { color: INK_SOFT, maxTicksLimit: 12 }, grid: { color: "#ece9f4" } },
        y: { title: { display: true, text: "cumulative waiting (vehicle-seconds)", color: INK_SOFT }, ticks: { color: INK_SOFT }, grid: { color: "#ece9f4" } },
      },
      plugins: { legend: { labels: { color: "#38324a", font: { family: "Outfit" } } } },
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

// single render loop drives every panel; interpolates between the last two frames
function renderLoop() {
  const now = performance.now();
  for (const p of Object.values(panels)) {
    if (!p.view || !p.cur) continue;
    let alpha = 1;
    if (!reduceMotion && p.prev) {
      const span = p.tCur - p.tPrev;
      alpha = span > 0 ? Math.min((now - p.tCur) / span, 1) : 1;
    }
    drawScene(p.view, p.cur, p.prev, alpha);
  }
  rafId = requestAnimationFrame(renderLoop);
}

function start() {
  const names = [...document.querySelectorAll("#ctrls input:checked")].map(i => i.value);
  if (!names.length) return alert("pick at least one controller");
  buildPanels(names);
  geometry = null;
  const wsProto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${wsProto}//${location.host}/ws`);
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
      geometry = msg.geometry;
      transform = makeTransform(geometry.bounds);
      roadLayer = buildRoadLayer(geometry, transform);
      signalHeads = buildSignalHeads(geometry, transform);
      for (const name of msg.controllers) {
        if (panels[name]) panels[name].view = { ctx: panels[name].ctx, T: transform, road: roadLayer, heads: signalHeads };
      }
      if (!rafId) rafId = requestAnimationFrame(renderLoop);
    } else if (msg.type === "frame") onFrame(msg);
    else if (msg.type === "done") setStatus("episode finished", false);
  };
  ws.onclose = () => { if (!document.getElementById("start").disabled) return; setStatus("idle", false); };
}

function onFrame(msg) {
  document.getElementById("status").textContent = `t = ${msg.time}s`;
  const now = performance.now();
  for (const [name, sim] of Object.entries(msg.sims)) {
    const p = panels[name];
    if (!p) continue;
    sim._byId = Object.create(null);
    for (const v of sim.vehicles) sim._byId[v[0]] = v;
    p.prev = p.cur; p.tPrev = p.tCur;
    p.cur = sim; p.tCur = now;
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
  if (!running && rafId) { cancelAnimationFrame(rafId); rafId = null; }
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
