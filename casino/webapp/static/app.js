"use strict";
/* Crash Casino — Telegram Mini App.
   Сервер (WebSocket) — источник правды по множителю; клиент только рисует. */

const TG = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
if (TG) { try { TG.ready(); TG.expand(); TG.setHeaderColor && TG.setHeaderColor("#0a0a16"); } catch (e) {} }

// Показ ошибок прямо на экране (нет доступа к консоли телефона) — диагностика фриза.
function showFatal(msg) {
  try {
    let bar = document.getElementById("errbar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "errbar";
      bar.style.cssText = "position:fixed;left:0;right:0;top:0;z-index:99999;background:#a3000c;color:#fff;" +
        "font:11px/1.4 monospace;padding:8px 10px;white-space:pre-wrap;word-break:break-word;";
      bar.addEventListener("click", () => bar.remove());
      (document.body || document.documentElement).appendChild(bar);
    }
    bar.textContent = "⚠ " + msg + "  (тап чтобы скрыть)";
  } catch (e) {}
}
window.addEventListener("error", (e) =>
  showFatal((e.message || "error") + " @ " + ((e.filename || "").split("/").pop()) + ":" + e.lineno));
window.addEventListener("unhandledrejection", (e) =>
  showFatal("promise: " + ((e.reason && (e.reason.message || e.reason)) || "rejection")));

// Лог событий на экране — только при открытии с ?debug, иначе не мешает.
const DEBUG = location.search.indexOf("debug") >= 0;
let _dbgLines = [];
function dbg(msg) {
  if (!DEBUG) return;
  try {
    _dbgLines.push(msg);
    if (_dbgLines.length > 6) _dbgLines.shift();
    let el = document.getElementById("dbgbar");
    if (!el) {
      el = document.createElement("div");
      el.id = "dbgbar";
      el.style.cssText = "position:fixed;left:0;right:0;bottom:58px;z-index:9998;background:rgba(0,0,0,.6);" +
        "color:#5f5;font:10px/1.3 monospace;padding:4px 8px;white-space:pre-wrap;pointer-events:none;";
      (document.body || document.documentElement).appendChild(el);
    }
    el.textContent = _dbgLines.join("\n");
  } catch (e) {}
}

function guestId() {
  let g = localStorage.getItem("guestId");
  if (!g) {
    g = (crypto.randomUUID && crypto.randomUUID()) || ("g" + Date.now() + Math.random().toString(36).slice(2));
    localStorage.setItem("guestId", g);
  }
  return g;
}

const $ = (id) => document.getElementById(id);
const rocketImg = new Image();
rocketImg.src = "/static/rocket.png?v=2";
const fmt = (nano) => {
  const t = nano / 1e9;
  return (Math.abs(t) >= 100 ? t.toFixed(0) : t.toFixed(2)).replace(/\.00$/, "");
};

/* ===================== Состояние ===================== */
const G = {
  ws: null, connected: false,
  state: "idle",            // idle | flying | crashed | cashed
  displayMult: 1, targetMult: 1, crashPoint: 0,
  balance: 0, cfg: { min: 0.1, max: 50, growth: 0.12, faucet: 100 },
  lastFair: null, pending: false,
  // визуал
  stars: [], particles: [], explosion: [], rocket: { x: 0, y: 0, ang: 0 },
};

/* ===================== WebSocket ===================== */
function connect() {
  // Гарантируем ОДНО соединение: глушим старое (без авто-реконнекта), затем открываем новое.
  if (G.ws) { try { G.ws.onclose = null; G.ws.onmessage = null; G.ws.close(); } catch (e) {} G.ws = null; }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  G.ws = ws;
  ws.onopen = () => {
    G.connected = true;
    dbg("ws OPEN");
    send({ type: "auth", initData: (TG && TG.initData) || "", guest: guestId() });
  };
  ws.onmessage = (e) => { try { handle(JSON.parse(e.data)); } catch (err) {} };
  ws.onclose = () => {
    G.connected = false;
    dbg("ws CLOSE");
    // Разморозка UI при обрыве связи — раунд на сервере уже завершился.
    if (G.state === "flying" || G.pending) {
      G.state = "idle"; G.pending = false; setAction("bet");
      $("status").textContent = "Связь потеряна, переподключаюсь…";
    }
    window.SlotGame && SlotGame.reset();
    setTimeout(connect, 1500);
  };
  ws.onerror = () => { try { ws.close(); } catch (e) {} };
}
function send(obj) {
  dbg("→ " + obj.type + " ws=" + (G.ws ? G.ws.readyState : "null"));
  if (G.ws && G.ws.readyState === 1) { G.ws.send(JSON.stringify(obj)); return true; }
  return false;
}
window.sendWS = send;

function handle(m) {
  G.lastMsg = Date.now();
  if (m.type === "dbg") { dbg("SRV " + m.msg); return; }
  dbg("← " + m.type + (typeof m.balance === "number" ? " bal=" + (m.balance / 1e9) : ""));
  if (typeof m.balance === "number") window.BAL = m.balance;
  if (m.type === "slot_result") { window.SlotGame && SlotGame.handle(m); return; }
  switch (m.type) {
    case "state":
      G.balance = m.balance;
      if (m.config) { G.cfg = m.config; clampAmount(); buildChips(); window.SlotGame && SlotGame.setConfig(m.config); }
      $("balance").textContent = fmt(m.balance);
      { const sb = $("sBal"); if (sb) sb.textContent = fmt(m.balance); }
      renderHistory(m.history || []);
      renderLeaderboard(m.leaderboard || []);
      renderRounds(m.history || []);
      break;
    case "started":
      G.lastFair = null;
      startFlight(m);
      break;
    case "tick":
      if (G.state === "flying") G.targetMult = m.m;
      break;
    case "crash":
      onCrash(m);
      break;
    case "cashout":
      onCashout(m);
      break;
    case "toast":
      toast(m.message);
      break;
    case "error":
      toast(m.message);
      G.pending = false;
      if (G.state !== "flying") resetIdle();
      window.SlotGame && SlotGame.reset();
      break;
  }
}

/* ===================== Игровые переходы ===================== */
function startFlight(m) {
  G.state = "flying"; G.pending = false;
  G.displayMult = 1; G.targetMult = 1;
  G.particles = []; G.explosion = [];
  G.balance = m.balance;
  $("balance").textContent = fmt(m.balance);
  $("mult").classList.remove("crashed");
  $("status").textContent = "Летим… забери вовремя!";
  setAction("cashout");
}

function onCrash(m) {
  G.state = "crashed"; G.pending = false;
  G.crashPoint = m.crashPoint; G.displayMult = m.crashPoint;
  G.balance = m.balance; $("balance").textContent = fmt(m.balance);
  G.lastFair = m;
  spawnExplosion();
  $("mult").classList.add("crashed");
  flash(); shake();
  $("status").innerHTML = `💥 Улетел на x${m.crashPoint.toFixed(2)} · 🎲 честность →`;
  if (m.outcome === "lose") buzz("error");
  setAction("disabled");
  setTimeout(resetIdle, 2600);
}

function onCashout(m) {
  G.state = "cashed"; G.pending = false;
  G.balance = m.balance; $("balance").textContent = fmt(m.balance);
  G.lastFair = m;
  $("status").innerHTML = `💸 Забрал x${m.m.toFixed(2)} · +${m.payoutStr} · 🎲 →`;
  buzz("success");
  toast(`+${m.payoutStr} 🎉`);
  setAction("disabled");
  setTimeout(resetIdle, 2600);
}

function resetIdle() {
  if (G.state === "flying") return;
  G.state = "idle";
  $("mult").classList.remove("crashed");
  $("mult").textContent = "x1.00";
  $("status").textContent = "Сделай ставку";
  setAction("bet");
}

/* ===================== Кнопка действия ===================== */
function setAction(mode) {
  const btn = $("action");
  btn.classList.remove("cashout", "disabled");
  if (mode === "bet") { btn.textContent = "Сделать ставку"; }
  else if (mode === "cashout") { btn.classList.add("cashout"); }
  else if (mode === "disabled") { btn.classList.add("disabled"); }
}

$("action").addEventListener("click", () => {
  dbg("tap СТАВКА st=" + G.state + " pend=" + G.pending + " bal=" + (window.BAL || 0) / 1e9);
  if (G.pending) return;
  buzz("light");
  if (G.state === "idle" || G.state === "crashed" || G.state === "cashed") {
    const amt = parseFloat($("amount").value.replace(",", "."));
    if (!amt || amt <= 0) { toast("Введи ставку"); return; }
    if (amt > (window.BAL || 0) / 1e9) { toast("Недостаточно монет — нажми ＋"); return; }
    if (!send({ type: "bet", amount: amt })) { toast("Нет связи, переподключаюсь…"); try { G.ws.close(); } catch (e) {} return; }
    G.pending = true; setAction("disabled");
  } else if (G.state === "flying") {
    if (!send({ type: "cashout" })) { toast("Нет связи, переподключаюсь…"); try { G.ws.close(); } catch (e) {} return; }
    G.pending = true;
  }
});

/* ===================== Ставка: контролы ===================== */
function curAmount() { return parseFloat($("amount").value.replace(",", ".")) || 0; }
function setAmount(v) {
  v = Math.max(G.cfg.min, Math.min(G.cfg.max, v));
  $("amount").value = (Math.round(v * 100) / 100).toString();
}
function clampAmount() { setAmount(curAmount() || G.cfg.min); }
$("inc").addEventListener("click", () => { setAmount(curAmount() + stepSize()); buzz("light"); });
$("dec").addEventListener("click", () => { setAmount(curAmount() - stepSize()); buzz("light"); });
function stepSize() { const a = curAmount(); return a < 1 ? 0.5 : a < 10 ? 1 : 5; }

function buildChips() {
  const presets = [0.5, 1, 5, 10, 25].filter((v) => v >= G.cfg.min && v <= G.cfg.max);
  const box = $("chips"); box.innerHTML = "";
  presets.forEach((v) => {
    const c = document.createElement("div");
    c.className = "chip"; c.textContent = v + " tTON";
    c.onclick = () => { setAmount(v); buzz("light"); };
    box.appendChild(c);
  });
}

/* ===================== Рендер списков ===================== */
function histClass(p) { return p < 2 ? "lo" : p < 10 ? "mid" : "hi"; }
function renderHistory(arr) {
  const box = $("history"); box.innerHTML = "";
  arr.forEach((p) => {
    const c = document.createElement("div");
    c.className = "hchip " + histClass(p); c.textContent = "x" + p.toFixed(2);
    box.appendChild(c);
  });
}
const AVA = ["#ff9f43", "#54a0ff", "#5f27cd", "#ff6b6b", "#1dd1a1", "#feca57", "#48dbfb", "#ff9ff3"];
function renderLeaderboard(arr) {
  const box = $("leaderboard"); box.innerHTML = "";
  if (!arr.length) { box.innerHTML = '<div class="lrow"><span class="lname" style="color:var(--muted)">Пока пусто — сыграй первым!</span></div>'; return; }
  arr.forEach((p, i) => {
    const row = document.createElement("div"); row.className = "lrow";
    const ava = document.createElement("div"); ava.className = "lava";
    ava.style.background = AVA[i % AVA.length]; ava.textContent = (p.name || "?")[0].toUpperCase();
    const name = document.createElement("div"); name.className = "lname"; name.textContent = (i + 1) + ". " + p.name;
    const bal = document.createElement("div"); bal.className = "lbal"; bal.textContent = "⭐ " + p.balanceStr;
    row.append(ava, name, bal); box.appendChild(row);
  });
}
function renderRounds(arr) {
  const box = $("rounds-list"); box.innerHTML = "";
  arr.forEach((p) => {
    const row = document.createElement("div"); row.className = "lrow";
    const tag = document.createElement("span"); tag.className = "rtag " + (p >= 2 ? "win" : "lose");
    tag.textContent = "x" + p.toFixed(2);
    const lbl = document.createElement("span"); lbl.className = "lname"; lbl.textContent = "Crash раунд";
    row.append(lbl, tag); box.appendChild(row);
  });
}

/* ===================== Навигация / прочее ===================== */
const VIEWS = ["lobby", "crash", "slot", "history"];
function switchView(v) {
  VIEWS.forEach((name) => $("view-" + name).classList.toggle("hidden", name !== v));
  document.querySelectorAll(".nav").forEach((b) => b.classList.toggle("active", b.dataset.view === v));
  // Crash рисуется на canvas: пока вьюха была скрыта, размер был 0 — пересчитываем.
  if (v === "crash") requestAnimationFrame(resize);
  if (v === "slot" && window.SlotGame) SlotGame.show();
  buzz("light");
}
window.switchView = switchView;
document.querySelectorAll(".nav").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});
document.querySelectorAll(".gamecard[data-game]").forEach((card) => {
  card.addEventListener("click", () => { if (window.Snd) Snd.unlock(); switchView(card.dataset.game); });
});
$("btnMusic").addEventListener("click", () => {
  if (window.Snd) { Snd.unlock(); const on = Snd.toggleMusic(); $("btnMusic").textContent = on ? "🔊" : "🔇"; }
});
$("btnFaucet").addEventListener("click", () => { dbg("tap +faucet"); buzz("light"); send({ type: "faucet" }); });
$("btnReferral").addEventListener("click", () => toast("Реферальная программа — скоро"));
window.toast = (msg) => toast(msg);
$("status").addEventListener("click", openFair);
$("fairClose").addEventListener("click", () => $("fairModal").classList.add("hidden"));
function openFair() {
  if (!G.lastFair) return;
  const f = G.lastFair;
  $("fairBody").innerHTML =
    `<b>Точка краша:</b> x${(f.crashPoint).toFixed(2)}<br><br>` +
    `<b>server_seed:</b><br><span class="mono">${f.serverSeed}</span><br><br>` +
    `<b>SHA-256(server_seed):</b><br><span class="mono">${f.hash}</span><br><br>` +
    `<b>client_seed:</b> <span class="mono">${f.clientSeed}</span><br>` +
    `<b>nonce:</b> ${f.nonce}<br><br>` +
    `Формула: HMAC-SHA256(server_seed, "client_seed:nonce") → множитель. ` +
    `Хэш был известен до раунда — результат не подделан.`;
  $("fairModal").classList.remove("hidden");
}

let toastT;
function toast(msg) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toastT); toastT = setTimeout(() => t.classList.remove("show"), 1800);
}
function buzz(kind) {
  if (TG && TG.HapticFeedback) {
    try {
      if (kind === "success") TG.HapticFeedback.notificationOccurred("success");
      else if (kind === "error") TG.HapticFeedback.notificationOccurred("error");
      else TG.HapticFeedback.impactOccurred("light");
    } catch (e) {}
  }
}
function flash() { const f = $("flash"); f.classList.remove("on"); void f.offsetWidth; f.classList.add("on"); }
function shake() { const w = document.querySelector(".mult-wrap"); w.classList.remove("shake"); void w.offsetWidth; w.classList.add("shake"); }

/* ===================== Canvas-анимация ===================== */
const cvs = $("game"), ctx = cvs.getContext("2d");
let W = 0, H = 0, DPR = 1;
function resize() {
  DPR = Math.min(window.devicePixelRatio || 1, 2);
  W = cvs.clientWidth; H = cvs.clientHeight;
  cvs.width = W * DPR; cvs.height = H * DPR;
  ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
  initStars();
}
function initStars() {
  G.stars = [];
  const n = Math.min(Math.floor((W * H) / 11000), 40);
  for (let i = 0; i < n; i++)
    G.stars.push({ x: Math.random() * W, y: Math.random() * H, r: Math.random() * 1.4 + 0.3, p: Math.random() * 6.28, s: Math.random() * 2 + 0.5 });
}

function multToProgress(m) { return 1 - 1 / (1 + 0.22 * (m - 1)); } // 0..1, насыщается

let _lastDraw = 0;
function draw(ts) {
  requestAnimationFrame(draw);
  // Не тратим ресурсы на отрисовку Crash, пока его экран не виден (важно для слабых телефонов).
  if (document.getElementById("view-crash").classList.contains("hidden")) return;
  if (ts - _lastDraw < 32) return;  // ограничение ~30 fps
  _lastDraw = ts;
  const t = ts / 1000;
  ctx.clearRect(0, 0, W, H);
  drawBg(t);

  // плавный множитель
  if (G.state === "flying") {
    G.displayMult += (G.targetMult - G.displayMult) * 0.2;
    if (G.displayMult < 1) G.displayMult = 1;
  }
  const shown = G.state === "crashed" ? G.crashPoint : G.displayMult;

  drawCurveAndRocket(t, shown);
  drawParticles();

  // текст множителя
  if (G.state === "flying" || G.state === "crashed" || G.state === "cashed") {
    $("mult").textContent = "x" + shown.toFixed(2);
    if (G.state === "flying") {
      $("action").textContent = "Забрать  x" + shown.toFixed(2);
    }
  }
}

function drawBg(t) {
  // звёзды
  for (const s of G.stars) {
    const a = 0.4 + 0.6 * Math.abs(Math.sin(t * s.s + s.p));
    ctx.globalAlpha = a; ctx.fillStyle = "#cdd3ff";
    ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, 6.28); ctx.fill();
  }
  ctx.globalAlpha = 1;
  // перспективная сетка
  const vx = W * 0.5, vy = H * 0.14;
  ctx.strokeStyle = "rgba(90,100,170,0.13)"; ctx.lineWidth = 1;
  const cols = 12;
  for (let i = 0; i <= cols; i++) {
    const x = (i / cols) * W * 2 - W * 0.5;
    ctx.beginPath(); ctx.moveTo(vx, vy); ctx.lineTo(x, H); ctx.stroke();
  }
  const scroll = (t * 0.25) % 1;
  for (let i = 0; i < 9; i++) {
    const f = (i + scroll) / 9;
    const y = vy + (H - vy) * (f * f);
    ctx.globalAlpha = 0.05 + 0.12 * f;
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function drawCurveAndRocket(t, mult) {
  const ox = W * 0.06, oy = H * 0.9;
  let rx, ry, ang;
  const flyingLike = G.state === "flying" || G.state === "crashed";

  if (flyingLike) {
    const p = multToProgress(mult);
    rx = ox + (W * 0.74) * p;
    ry = oy - (H * 0.66) * p;
    const cpx = ox + (rx - ox) * 0.55, cpy = oy;
    // заливка под кривой
    const grad = ctx.createLinearGradient(0, ry, 0, oy);
    const col = G.state === "crashed" ? "255,77,94" : "57,255,139";
    grad.addColorStop(0, `rgba(${col},0.32)`); grad.addColorStop(1, `rgba(${col},0)`);
    ctx.beginPath(); ctx.moveTo(ox, oy);
    ctx.quadraticCurveTo(cpx, cpy, rx, ry);
    ctx.lineTo(rx, oy); ctx.closePath(); ctx.fillStyle = grad; ctx.fill();
    // линия кривой
    ctx.beginPath(); ctx.moveTo(ox, oy);
    ctx.quadraticCurveTo(cpx, cpy, rx, ry);
    ctx.strokeStyle = G.state === "crashed" ? "#ff4d5e" : "#39ff8b";
    ctx.lineWidth = 4; ctx.stroke();
    ang = Math.atan2(ry - cpy, rx - cpx);
  } else {
    rx = ox + W * 0.18; ry = oy - H * 0.08 + Math.sin(t * 2) * 8; ang = -0.5;
  }
  G.rocket = { x: rx, y: ry, ang };

  // --- "живость": турбулентность усиливается с ростом множителя ---
  const flying = G.state === "flying";
  const turb = flying ? Math.min(0.6 + (mult - 1) * 0.22, 4.5) : 0.5;
  const jx = (Math.sin(t * 41) + Math.sin(t * 23 + 1.3)) * 0.5 * turb + (Math.random() - 0.5) * turb;
  const jy = (Math.sin(t * 37 + 0.7) + Math.sin(t * 29 + 2.1)) * 0.5 * turb + (Math.random() - 0.5) * turb;
  const bob = Math.sin(t * 3) * (flying ? 1.6 : 3.2);
  const wob = Math.sin(t * 9) * 0.03 + Math.sin(t * 5.5 + 1) * 0.02 + (flying ? (Math.random() - 0.5) * 0.03 : 0);
  const kick = Math.sin(t * 13) * (flying ? 0.07 : 0.025); // "дрыганье" через squash/stretch

  // выхлоп — пышнее и ярче во время полёта
  if (flying) {
    for (let q = 0; q < 2; q++) {
      G.particles.push({
        x: rx - Math.cos(ang) * 20, y: ry - Math.sin(ang) * 20,
        vx: -Math.cos(ang) * (1.4 + Math.random()) + (Math.random() - 0.5) * 1.7,
        vy: -Math.sin(ang) * (1.4 + Math.random()) + (Math.random() - 0.5) * 1.7 + 0.5,
        life: 1, r: Math.random() * 5 + 2.5,
        c: Math.random() < 0.5 ? "255,190,70" : (Math.random() < 0.6 ? "255,110,40" : "255,70,30"),
      });
    }
  }

  if (G.state !== "crashed") {
    ctx.save();
    ctx.translate(rx + jx, ry + jy + bob);
    ctx.rotate(ang + 0.6 + wob); // спрайт уже смотрит вверх-вправо
    ctx.scale(1 + kick * 0.18, 1 - kick * 0.18);
    if (rocketImg.complete && rocketImg.naturalWidth) {
      const w = 82, h = w * rocketImg.naturalHeight / rocketImg.naturalWidth;
      ctx.drawImage(rocketImg, -w / 2, -h / 2, w, h);
    } else {
      ctx.font = "44px serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText("🚀", 0, 0);
    }
    ctx.restore();
  }
}

function spawnExplosion() {
  const { x, y } = G.rocket;
  for (let i = 0; i < 38; i++) {
    const a = Math.random() * 6.28, sp = Math.random() * 6 + 2;
    G.explosion.push({ x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp, life: 1, r: Math.random() * 5 + 2,
      c: ["255,77,94", "255,160,60", "255,210,80"][i % 3] });
  }
}
function drawParticles() {
  for (const arr of [G.particles, G.explosion]) {
    for (let i = arr.length - 1; i >= 0; i--) {
      const p = arr[i];
      p.x += p.vx; p.y += p.vy; p.vy += 0.06; p.life -= 0.03;
      if (p.life <= 0) { arr.splice(i, 1); continue; }
      ctx.globalAlpha = Math.max(0, p.life); ctx.fillStyle = `rgb(${p.c})`;
      ctx.beginPath(); ctx.arc(p.x, p.y, p.r * p.life, 0, 6.28); ctx.fill();
    }
  }
  ctx.globalAlpha = 1;
}

/* ===================== Старт ===================== */
window.addEventListener("resize", resize);
buildChips();
resize();
requestAnimationFrame(draw);
if (window.SlotGame) SlotGame.init();
// Сторож: если во время полёта тики пропали (обрыв WS) — переподключаемся, чтобы не зависало.
setInterval(() => {
  if (G.state === "flying" && G.ws && Date.now() - (G.lastMsg || 0) > 4000) {
    try { G.ws.close(); } catch (e) {}
  }
}, 1500);
// Разблокировать звук при первом касании.
document.addEventListener("pointerdown", function unlockOnce() {
  if (window.Snd) Snd.unlock();
  document.removeEventListener("pointerdown", unlockOnce);
}, { once: true });
connect();
