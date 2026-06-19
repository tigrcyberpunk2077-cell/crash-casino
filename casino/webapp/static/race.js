"use strict";
/* «Забег барана» — мультиплеер-джекпот. Общий раунд на всех; больше ставка —
   больше кусок поля и выше шанс. Баран бежит, пастух ловит его в точке f —
   чей кусок, тот забирает банк. window.RaceGame */
(function () {
  // Роли = темы-украшения куска поля. Можно переименовывать/добавлять:
  // id — внутренний код, name — подпись, emoji — узор поля, c1/c2 — градиент.
  const ROLES = [
    { id: "samir",   name: "Самир",  emoji: "🌹", c1: "#ff5d8f", c2: "#c9184a" },
    { id: "gold",    name: "Золото", emoji: "🪙", c1: "#ffd34d", c2: "#d98e00" },
    { id: "viking",  name: "Викинг", emoji: "⚔️", c1: "#6ec3ff", c2: "#2a6fdb" },
    { id: "snake",   name: "Змей",   emoji: "🐍", c1: "#5be37a", c2: "#1f9d4d" },
    { id: "fire",    name: "Огонь",  emoji: "🔥", c1: "#ff9b3d", c2: "#e0360d" },
    { id: "skull",   name: "Череп",  emoji: "💀", c1: "#c7b8ff", c2: "#6b46ff" },
    { id: "ice",     name: "Лёд",    emoji: "❄️", c1: "#a8f0ff", c2: "#27a9cf" },
    { id: "diamond", name: "Алмаз",  emoji: "💎", c1: "#7fffd4", c2: "#13a3a3" },
  ];
  const roleById = (id) => ROLES.find((r) => r.id === id) || ROLES[0];

  const $ = (id) => document.getElementById(id);
  let myRole = ROLES[0].id;
  let bet = 1, cfg = { min: 0.1, max: 50 };
  let players = [], phase = "waiting", potStr = "0", recent = [];
  let endsIn = 0, roundSec = 30, ticker = null, revealing = false, lastReveal = null, _anim = null;
  let betBusy = false, _betT = null;

  function isVisible() {
    const v = $("view-jackpot");
    return v && !v.classList.contains("hidden");
  }

  /* ---------- роли (выбор темы) ---------- */
  function buildRoles() {
    const strip = $("roleStrip"); if (!strip) return;
    strip.innerHTML = "";
    ROLES.forEach((r) => {
      const chip = document.createElement("button");
      chip.className = "role-chip" + (r.id === myRole ? " sel" : "");
      chip.dataset.role = r.id;
      chip.style.setProperty("--c1", r.c1);
      chip.style.setProperty("--c2", r.c2);
      chip.innerHTML = `<span class="re">${r.emoji}</span><span>${r.name}</span>`;
      chip.onclick = () => {
        myRole = r.id;
        strip.querySelectorAll(".role-chip").forEach((c) => c.classList.toggle("sel", c.dataset.role === r.id));
        if (window.Snd) Snd.click();
      };
      strip.appendChild(chip);
    });
  }

  /* ---------- поле (куски) ---------- */
  function renderField() {
    const zones = $("raceZones"); if (!zones) return;
    zones.innerHTML = "";
    if (!players.length) {
      const z = document.createElement("div");
      z.className = "rzone empty";
      z.innerHTML = `<div class="rz-label">Поле пустое<br><small>выбери роль и поставь</small></div>`;
      zones.appendChild(z);
      return;
    }
    players.forEach((p) => {
      const r = roleById(p.role);
      const z = document.createElement("div");
      z.className = "rzone";
      z.dataset.id = p.id;
      z.style.flexGrow = Math.max(p.pct, 3);
      z.style.background = `linear-gradient(135deg, ${r.c1}, ${r.c2})`;
      const mine = window.MY_ID && p.id === window.MY_ID;
      z.innerHTML =
        `<div class="rz-pattern">${r.emoji.repeat(14)}</div>` +
        `<div class="rz-label"><b>${p.name}${mine ? " (ты)" : ""}</b>` +
        `<small>${p.amountStr} · ${p.pct}%</small></div>`;
      zones.appendChild(z);
    });
    renderFences();
  }

  // Границы кусков = заборы, которые баран перепрыгивает.
  function fenceBoundaries() {
    const b = [];
    let cum = 0;
    for (let i = 0; i < players.length - 1; i++) { cum += players[i].pct / 100; b.push(cum); }
    return b;
  }
  function renderFences() {
    const box = $("raceFences"); if (!box) return;
    box.innerHTML = "";
    fenceBoundaries().forEach((bx) => {
      const f = document.createElement("div");
      f.className = "fence"; f.style.left = (bx * 100) + "%";
      box.appendChild(f);
    });
  }

  function renderPlayers() {
    const box = $("racePlayers"); if (!box) return;
    box.innerHTML = "";
    if (!players.length) {
      box.innerHTML = `<div class="rp-empty">Пока никто не поставил. Будь первым! 🐏</div>`;
    } else {
      players.forEach((p) => {
        const r = roleById(p.role);
        const row = document.createElement("div");
        row.className = "rp-row";
        row.innerHTML =
          `<span class="rp-dot" style="background:${r.c1}">${r.emoji}</span>` +
          `<span class="rp-name">${p.name}</span>` +
          `<span class="rp-amt">${p.amountStr}</span>` +
          `<span class="rp-pct">${p.pct}%</span>`;
        box.appendChild(row);
      });
    }
    if (recent.length) {
      const w = recent[0];
      const last = document.createElement("div");
      last.className = "rp-last";
      last.innerHTML = `🏆 Прошлый раунд: <b>${w.name}</b> ${roleById(w.role).emoji} забрал <b>${w.amountStr}</b>`;
      box.appendChild(last);
    }
  }

  function renderHead() {
    if ($("racePot")) $("racePot").textContent = potStr;
  }

  /* ---------- таймер ---------- */
  function stopTicker() { if (ticker) { clearInterval(ticker); ticker = null; } }
  function startTicker() {
    stopTicker();
    ticker = setInterval(() => {
      if (phase !== "collecting") { stopTicker(); return; }
      endsIn = Math.max(0, endsIn - 0.25);
      paintTimer();
    }, 250);
  }
  function paintTimer() {
    const el = $("raceTimer"); if (!el) return;
    if (phase === "collecting") {
      el.textContent = "⏱ " + Math.ceil(endsIn) + "с";
      el.classList.toggle("hot", endsIn <= 5);
    } else if (phase === "reveal") {
      el.textContent = "🐏 Забег!";
      el.classList.remove("hot");
    } else {
      el.textContent = "Ждём ставку";
      el.classList.remove("hot");
    }
  }

  /* ---------- приём сообщений ---------- */
  function onSnapshot(m) {
    if (revealing && m.phase !== "waiting") return; // не перетираем идущую анимацию
    revealing = false;
    phase = m.phase; players = m.players || []; potStr = m.potStr || "0";
    recent = m.recent || []; endsIn = m.endsIn || 0; roundSec = m.roundSec || 30;
    if ($("raceHash")) $("raceHash").textContent = (m.hash || "").slice(0, 16) + "…";
    resetActors();
    renderField(); renderPlayers(); renderHead(); paintTimer();
    if (phase === "collecting") startTicker(); else stopTicker();
    setBetBusy(false); clearTimeout(_betT);
  }
  function onTimer(m) {
    if (phase === "collecting") { endsIn = m.endsIn; paintTimer(); }
  }

  /* ---------- анимация забега ---------- */
  function resetActors() {
    if (_anim) { cancelAnimationFrame(_anim); _anim = null; }
    if (window.Snd) Snd.hoofStop();
    const ram = $("raceRam"), shep = $("raceShep"), win = $("raceWinner");
    if (!ram) return;
    ram.style.transition = "none"; shep.style.transition = "none";
    ram.style.left = "2%"; shep.style.left = "-12%";
    ram.style.transform = "translate(-50%,-6px)"; shep.style.transform = "translate(-50%,-6px)";
    ram.classList.remove("caught"); win.classList.remove("show"); win.textContent = "";
    void ram.offsetWidth;
  }

  // easeInOutQuad с мелкими «спотыканиями» (рывки скорости).
  function eased(p) {
    let e = p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2;
    e += Math.sin(p * Math.PI * 7) * 0.018 * (1 - p);   // микро-рывки
    return Math.max(0, Math.min(1, e));
  }

  function onReveal(m) {
    revealing = true; lastReveal = m;
    phase = "reveal"; players = m.players || []; potStr = m.potStr || potStr;
    stopTicker(); renderField(); renderPlayers(); renderHead(); paintTimer();
    if (window.Snd) { Snd.baa(); Snd.hoofStart(); }   // старт забега: баран блеет и скачет

    const ram = $("raceRam"), shep = $("raceShep"), win = $("raceWinner");
    if (!ram) { if (window.Snd) Snd.hoofStop(); return; }
    resetActors();

    const f = Math.max(0, Math.min(0.999, m.f));
    const startX = 0.03, endX = f * 0.92 + 0.05;     // доли ширины (0..1)
    const fences = fenceBoundaries();
    const RUN = 7000;                                  // мс бега — длиннее и интереснее
    const t0 = performance.now();
    let fenceHopSnd = fences.map(() => false);

    function liftAt(x, p, phase0, hopFreq, hopAmp) {
      const weave = Math.sin(p * Math.PI * 5 + phase0) * 9;            // виляет вверх-вниз
      const hop = Math.max(0, Math.sin(p * Math.PI * hopFreq + phase0)) * hopAmp; // мелкие прыжки
      let fenceLift = 0;
      for (let i = 0; i < fences.length; i++) {
        const d = Math.abs(x - fences[i]);
        if (d < 0.07) {                                                // у забора — большой прыжок
          fenceLift = Math.max(fenceLift, Math.sin((1 - d / 0.07) * Math.PI) * 48);
          if (!fenceHopSnd[i] && d < 0.012) { fenceHopSnd[i] = true; if (window.Snd) Snd.click(); }
        }
      }
      return { lift: 6 + weave + hop + fenceLift, jump: hop + fenceLift };
    }

    function frame(now) {
      const p = Math.min(1, (now - t0) / RUN);
      const e = eased(p);
      const x = startX + (endX - startX) * e;
      const rl = liftAt(x, p, 0, 9, 13);
      const stumble = (p > 0.12 && p < 0.92) ? Math.sin(p * Math.PI * 14) * 5 : 0;
      const tilt = -rl.jump * 0.32 + stumble;          // нос вверх в прыжке + покачивание
      ram.style.left = (x * 100) + "%";
      ram.style.transform = `translate(-50%, ${-rl.lift}px) rotate(${tilt}deg)`;

      const se = Math.max(0, e - 0.2);                 // пастух бежит позади, держит расстояние
      const sx = startX + (endX - startX) * se;
      const sl = liftAt(sx, p, 1.1, 8, 10);
      shep.style.left = (sx * 100) + "%";
      shep.style.transform = `translate(-50%, ${-sl.lift}px) rotate(${-sl.jump * 0.26}deg)`;

      if (p < 1) { _anim = requestAnimationFrame(frame); }
      else { _anim = null; caught(); }
    }

    function caught() {
      ram.classList.add("caught");
      if (window.Snd) { Snd.hoofStop(); Snd.baa(); Snd.click(); }   // догнал — баран блеет
      const zone = $("raceZones").querySelector(`.rzone[data-id="${m.winnerId}"]`);
      if (zone) zone.classList.add("win");
      const mine = window.MY_ID && m.winnerId === window.MY_ID;
      win.innerHTML = (mine ? "🎉 ТЫ ЗАБРАЛ!<br>" : `🏆 ${m.winnerName} ${roleById(m.winnerRole).emoji}<br>`) +
        `<span class="rw-amt">+${m.payoutStr}</span>`;
      win.classList.add("show");
      if (TGref()) { try { TGref().HapticFeedback.notificationOccurred(mine ? "success" : "warning"); } catch (e) {} }
      if (mine && window.sendWS) window.sendWS({ type: "auth", initData: (TGref() && TGref().initData) || "", guest: localStorage.getItem("guestId") || "" });
    }

    _anim = requestAnimationFrame(frame);
  }
  function TGref() { return window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null; }

  /* ---------- ставка / контролы ---------- */
  function setBet(v) {
    v = Math.max(cfg.min, Math.min(cfg.max, v));
    bet = Math.round(v * 100) / 100;
    if ($("raceAmount")) $("raceAmount").value = bet.toString();
  }
  function setBetBusy(b) {
    betBusy = b;
    const btn = $("raceBet"); if (!btn) return;
    btn.classList.toggle("disabled", b);
    btn.textContent = b ? "Ставлю…" : "Поставить на поле";
  }
  function doBet() {
    if (betBusy) return;
    if (revealing || phase === "reveal") { window.toast && toast("Подожди следующий раунд"); return; }
    const amt = parseFloat(($("raceAmount").value || "").replace(",", ".")) || bet;
    if (!amt || amt <= 0) { window.toast && toast("Введи ставку"); return; }
    if (amt > (window.BAL || 0) / 1e9) { window.toast && toast("Недостаточно монет — нажми ＋"); return; }
    if (window.Snd) Snd.click();
    if (window.sendWS && window.sendWS({ type: "jackpot_bet", amount: amt, role: myRole })) {
      setBetBusy(true);                              // мгновенный отклик
      clearTimeout(_betT); _betT = setTimeout(() => setBetBusy(false), 4000);  // страховка
    }
  }

  function showFair() {
    if (!lastReveal) { window.toast && toast("Сыграй раунд — появится проверка"); return; }
    const f = lastReveal;
    const body = $("fairBody"); if (!body) return;
    body.innerHTML =
      `<b>Точка поимки f:</b> ${f.f.toFixed(6)}<br><br>` +
      `<b>server_seed:</b><br><span class="mono">${f.serverSeed}</span><br><br>` +
      `<b>SHA-256(server_seed):</b><br><span class="mono">${f.hash}</span><br><br>` +
      `<b>round_id:</b> <span class="mono">${f.roundId}</span><br><br>` +
      `f = HMAC-SHA256(server_seed, round_id). Хэш был известен до ставок — ` +
      `сервер не мог подстроить победителя.`;
    $("fairModal").classList.remove("hidden");
  }

  const RaceGame = {
    init() {
      buildRoles(); setBet(1); resetActors();
      renderField(); renderPlayers(); paintTimer();
      $("raceBet").onclick = doBet;
      $("raceInc").onclick = () => { setBet(bet + (bet < 1 ? 0.5 : bet < 10 ? 1 : 5)); if (window.Snd) Snd.click(); };
      $("raceDec").onclick = () => { setBet(bet - (bet <= 1 ? 0.5 : bet <= 10 ? 1 : 5)); if (window.Snd) Snd.click(); };
      if ($("raceFair")) $("raceFair").onclick = showFair;
    },
    setConfig(c) { if (c) { cfg = c; setBet(Math.max(cfg.min, Math.min(bet, cfg.max))); } },
    handle(m) {
      if (m.type === "jackpot") onSnapshot(m);
      else if (m.type === "jackpot_timer") onTimer(m);
      else if (m.type === "jackpot_reveal") onReveal(m);
    },
    show() { if (window.Snd) { Snd.unlock(); Snd.setTrack("ramin"); } if (window.sendWS) window.sendWS({ type: "jackpot_join" }); },
    maybeRejoin() { if (isVisible() && window.sendWS) window.sendWS({ type: "jackpot_join" }); },
    onBalance() { setBetBusy(false); clearTimeout(_betT); },
    reset() { /* при обрыве связи ничего разрушать не нужно — придёт свежий snapshot */ },
  };
  window.RaceGame = RaceGame;
})();
