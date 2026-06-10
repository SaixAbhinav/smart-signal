// SmartSignal dashboard: renders lockstep simulations streamed over WebSocket.

const COLORS = { fixed: "#e57373", actuated: "#ffb74d", maxpressure: "#64b5f6", rl: "#81c784" };
const LABELS = { fixed: "Fixed timer", actuated: "Actuated (SUMO)", maxpressure: "Max-pressure", rl: "PPO agent (RL)" };
const SIGNAL = { green: "#2ecc71", yellow: "#f1c40f", red: "#e74c3c" };

// --- intersection geometry (320x320 canvas, right-hand traffic) -------------
const C = 160, HALF = 42, LW = 14, BOX = [C - HALF, C + HALF];
// per approach: cross-axis position of lane idx (0=driver's right ... 2=left)
function laneRect(dir, idx) {
  switch (dir) {
    case "N": return { x: 118 + idx * LW, y: 0, w: LW, h: 118, vert: true, stop: 118, dq: -1 };
    case "S": return { x: 188 - idx * LW, y: 202, w: LW, h: 118, vert: true, stop: 202, dq: 1 };
    case "E": return { x: 202, y: 118 + idx * LW, w: 118, h: LW, vert: false, stop: 202, dq: 1 };
    case "W": return { x: 0, y: 188 - idx * LW, w: 118, h: LW, vert: false, stop: 118, dq: -1 };
  }
}
const MOVE_GLYPH = ["→", "↑", "↰"]; // lane 0 right+straight, 1 straight, 2 left

function drawIntersection(ctx, lanes, colors, queues) {
  ctx.clearRect(0, 0, 320, 320);
  // road surfaces: 84px bands (3 lanes each way), junction box slightly lighter
  ctx.fillStyle = "#2b2f33";
  ctx.fillRect(BOX[0], 0, HALF * 2, 320);
  ctx.fillRect(0, BOX[0], 320, HALF * 2);
  ctx.fillStyle = "#3a3f44";
  ctx.fillRect(BOX[0], BOX[0], HALF * 2, HALF * 2);
  // center lines
  ctx.strokeStyle = "#555c44";
  ctx.beginPath();
  ctx.moveTo(C, 0); ctx.lineTo(C, BOX[0]); ctx.moveTo(C, BOX[1]); ctx.lineTo(C, 320);
  ctx.moveTo(0, C); ctx.lineTo(BOX[0], C); ctx.moveTo(BOX[1], C); ctx.lineTo(320, C);
  ctx.stroke();

  for (const lane of lanes) {
    const [dir, , idxStr] = lane.split("_");
    const idx = +idxStr;
    const r = laneRect(dir, idx);
    // lane outline
    ctx.strokeStyle = "#1f2428";
    ctx.strokeRect(r.x + 0.5, r.y + 0.5, r.w - 1, r.h - 1);
    // queue bar grows away from the stop line
    const q = Math.min(queues[lane] || 0, 22);
    if (q > 0) {
      ctx.fillStyle = "rgba(231, 76, 60, 0.75)";
      const len = q * 5;
      if (r.vert) ctx.fillRect(r.x + 2, r.dq < 0 ? r.stop - len : r.stop, r.w - 4, len);
      else ctx.fillRect(r.dq < 0 ? r.stop - len : r.stop, r.y + 2, len, r.h - 4);
    }
    // signal head at the stop line
    ctx.fillStyle = SIGNAL[colors[lane]] || "#555";
    if (r.vert) ctx.fillRect(r.x + 2, r.dq < 0 ? r.stop - 5 : r.stop + 1, r.w - 4, 4);
    else ctx.fillRect(r.dq < 0 ? r.stop - 5 : r.stop + 1, r.y + 2, 4, r.h - 4);
  }
  // compass labels
  ctx.fillStyle = "#8b98a5";
  ctx.font = "11px sans-serif";
  ctx.fillText("N", 154, 12); ctx.fillText("S", 154, 314);
  ctx.fillText("W", 6, 164); ctx.fillText("E", 306, 164);
}

// --- app state ---------------------------------------------------------------
let ws = null, chart = null, panels = {}, lanes = [];

async function init() {
  const cfg = await (await fetch("/api/config")).json();
  const profileSel = document.getElementById("profile");
  cfg.profiles.forEach(p => profileSel.add(new Option(p, p)));
  const ctrls = document.getElementById("ctrls");
  for (const c of cfg.controllers) {
    const checked = c !== "maxpressure" ? "checked" : "";
    ctrls.insertAdjacentHTML("beforeend",
      `<label><input type="checkbox" value="${c}" ${checked}> ${LABELS[c]}</label>`);
  }
  if (!cfg.rl_available) {
    ctrls.insertAdjacentHTML("beforeend",
      `<label style="color:#666">(train a model to enable RL)</label>`);
  }
}

function buildPanels(names) {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  panels = {};
  for (const name of names) {
    const div = document.createElement("div");
    div.className = "sim-panel";
    div.innerHTML = `
      <h3 style="color:${COLORS[name]}">${LABELS[name]}</h3>
      <canvas width="320" height="320"></canvas>
      <div class="stats">
        <span>queued<b class="q">0</b></span>
        <span>throughput<b class="a">0</b></span>
        <span>total wait<b class="w">0s</b></span>
      </div>`;
    grid.appendChild(div);
    panels[name] = {
      ctx: div.querySelector("canvas").getContext("2d"),
      q: div.querySelector(".q"), a: div.querySelector(".a"), w: div.querySelector(".w"),
    };
  }
  if (chart) chart.destroy();
  chart = new Chart(document.getElementById("chart"), {
    type: "line",
    data: {
      labels: [],
      datasets: names.map(n => ({
        label: LABELS[n], data: [], borderColor: COLORS[n],
        pointRadius: 0, borderWidth: 2, tension: 0.3,
      })),
    },
    options: {
      animation: false, responsive: true, maintainAspectRatio: false,
      scales: {
        x: { title: { display: true, text: "simulation time (s)", color: "#8b98a5" }, ticks: { color: "#8b98a5", maxTicksLimit: 12 }, grid: { color: "#2a3441" } },
        y: { title: { display: true, text: "cumulative waiting (vehicle-seconds)", color: "#8b98a5" }, ticks: { color: "#8b98a5" }, grid: { color: "#2a3441" } },
      },
      plugins: { legend: { labels: { color: "#e6e9ec" } } },
    },
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
      profile: document.getElementById("profile").value,
      seed: +document.getElementById("seed").value,
      controllers: names,
      speed: +document.getElementById("speed").value,
    }));
    setStatus("running", true);
  };
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.type === "init") lanes = msg.lanes;
    else if (msg.type === "frame") onFrame(msg);
    else if (msg.type === "done") setStatus("episode finished", false);
  };
  ws.onclose = () => setStatus("idle", false);
}

function onFrame(msg) {
  document.getElementById("status").textContent = `t = ${msg.time}s`;
  for (const [name, sim] of Object.entries(msg.sims)) {
    const p = panels[name];
    if (!p) continue;
    drawIntersection(p.ctx, lanes, sim.colors, sim.queues);
    p.q.textContent = sim.metrics.queued;
    p.a.textContent = sim.metrics.arrived;
    p.w.textContent = (sim.metrics.cum_wait / 60).toFixed(0) + " veh·min";
  }
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
  document.getElementById("status").textContent = text;
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
