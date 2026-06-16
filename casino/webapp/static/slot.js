"use strict";
/* Слот «Дикий Запад»: анимация крутки, каскадов, множителя, фриспинов. window.SlotGame */
(function () {
  const REELS = 5, ROWS = 3;
  const LADDER = [1, 2, 4, 8, 16, 32, 64, 128];
  const LOWS = { J: "low-j", Q: "low-q", K: "low-k", A: "low-a" };
  const ALL = ["J", "Q", "K", "A", "H3", "H2", "H1", "W", "S"];

  let busy = false, turbo = false, auto = false, bet = 1, cfg = { min: 0.1, max: 50 };
  let runWin = 0;

  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((r) => setTimeout(r, turbo ? ms * 0.35 : ms));
  const rand = (a) => a[(Math.random() * a.length) | 0];

  function symHTML(id) {
    if (LOWS[id]) return `<div class="sym lowsym ${LOWS[id]}">${id}</div>`;
    if (id === "W") return `<div class="sym wildsym">WILD</div>`;
    if (id === "S") return `<div class="sym scatsym">SCATTER</div>`;
    return `<div class="sym imgsym"><img src="/static/slot/${id.toLowerCase()}.png?v=4" alt=""></div>`;
  }

  function buildGrid() {
    const g = $("slotGrid"); g.innerHTML = "";
    for (let r = 0; r < REELS; r++) {
      const col = document.createElement("div"); col.className = "reel"; col.dataset.reel = r;
      for (let row = 0; row < ROWS; row++) {
        const c = document.createElement("div"); c.className = "cell"; c.dataset.row = row;
        c.innerHTML = symHTML(rand(["J", "Q", "K", "A"]));
        col.appendChild(c);
      }
      g.appendChild(col);
    }
  }
  function buildLadder() {
    const l = $("ladder"); l.innerHTML = "";
    LADDER.forEach((m) => {
      const d = document.createElement("div"); d.className = "rung"; d.dataset.m = m;
      d.textContent = "x" + m; l.appendChild(d);
    });
  }
  function setLadder(m) {
    document.querySelectorAll("#ladder .rung").forEach((el) => {
      el.classList.toggle("on", +el.dataset.m === m);
      el.classList.toggle("passed", +el.dataset.m < m);
    });
  }
  function cell(reel, row) { return document.querySelector(`#slotGrid .reel[data-reel="${reel}"] .cell[data-row="${row}"]`); }

  function renderGrid(grid, drop) {
    for (let r = 0; r < REELS; r++)
      for (let row = 0; row < ROWS; row++) {
        const c = cell(r, row);
        c.className = "cell" + (drop ? " drop" : "");
        c.innerHTML = symHTML(grid[r][row]);
      }
  }

  function spinReels(targetGrid) {
    return new Promise((resolve) => {
      let stopped = 0;
      for (let r = 0; r < REELS; r++) {
        const col = $("slotGrid").children[r];
        col.classList.add("spinning");
        const iv = setInterval(() => {
          for (let row = 0; row < ROWS; row++) col.children[row].innerHTML = symHTML(rand(ALL));
        }, 60);
        const delay = (turbo ? 120 : 300) + r * (turbo ? 70 : 160);
        setTimeout(() => {
          clearInterval(iv); col.classList.remove("spinning");
          for (let row = 0; row < ROWS; row++) col.children[row].innerHTML = symHTML(targetGrid[r][row]);
          if (window.Snd) Snd.reelStop();
          if (++stopped === REELS) resolve();
        }, delay);
      }
    });
  }

  function highlight(wins) {
    let maxReels = 0;
    wins.forEach((w) => { maxReels = Math.max(maxReels, w.reels); w.pos.forEach(([r, row]) => cell(r, row).classList.add("win")); });
    return maxReels;
  }
  function clearHighlight() { document.querySelectorAll("#slotGrid .cell.win").forEach((c) => c.classList.remove("win")); }

  async function explodeTo(nextGrid) {
    document.querySelectorAll("#slotGrid .cell.win").forEach((c) => c.classList.add("explode"));
    if (window.Snd) Snd.cascade();
    await sleep(220);
    renderGrid(nextGrid, true);
    await sleep(180);
  }

  function setWin(v) { runWin = v; $("sWin").textContent = (v).toFixed(2); }

  async function playFrames(frames) {
    renderGrid(frames[0].grid);
    await sleep(120);
    for (let i = 0; i < frames.length; i++) {
      const f = frames[i];
      if (f.wins && f.wins.length) {
        setLadder(f.mult);
        if (f.mult > 1 && window.Snd) Snd.multUp(LADDER.indexOf(f.mult));
        const lvl = highlight(f.wins);
        if (window.Snd) Snd.win(lvl);
        setWin(runWin + f.win);
        $("slotBanner").textContent = "+" + f.win.toFixed(2) + (f.mult > 1 ? "  x" + f.mult : "");
        $("slotBanner").className = "slot-banner show win";
        await sleep(600);
        if (i + 1 < frames.length) await explodeTo(frames[i + 1].grid);
        clearHighlight();
      } else break;
    }
  }

  async function animate(m) {
    runWin = 0; setWin(0);
    setLadder(1);
    const rounds = m.rounds;
    // базовый раунд
    if (window.Snd) Snd.spin();
    await spinReels(rounds[0].frames[0].grid);
    await playFrames(rounds[0].frames);

    // фриспины
    const frees = rounds.slice(1);
    if (frees.length) {
      $("slotBanner").textContent = "🎁 ФРИСПИНЫ x" + frees.length;
      $("slotBanner").className = "slot-banner show bonus";
      if (window.Snd) Snd.bonus();
      await sleep(turbo ? 500 : 1300);
      for (let s = 0; s < frees.length; s++) {
        $("slotBanner").textContent = "ФРИСПИН " + (s + 1) + " / " + frees.length;
        if (window.Snd) Snd.spin();
        await spinReels(frees[s].frames[0].grid);
        await playFrames(frees[s].frames);
      }
    }

    // итог
    clearHighlight();
    if (m.payout > 0) {
      const big = m.total >= 20;
      if (window.Snd) (big ? Snd.bigwin() : Snd.win(3));
      $("slotBanner").textContent = "🏆 ВЫИГРЫШ " + m.payoutStr + (big ? "  МЕГА!" : "");
      $("slotBanner").className = "slot-banner show " + (big ? "mega" : "win");
    } else {
      if (window.Snd) Snd.lose();
      $("slotBanner").textContent = "";
      $("slotBanner").className = "slot-banner";
    }
    if (m.balanceStr) $("balance").textContent = (m.balance / 1e9 >= 100 ? (m.balance / 1e9).toFixed(0) : (m.balance / 1e9).toFixed(2));

    busy = false;
    enable(true);
    if (auto && document.getElementById("view-slot").classList.contains("hidden") === false) {
      await sleep(900);
      if (auto) doSpin(false);
    }
  }

  function enable(on) {
    ["sSpin", "sBuy", "sInc", "sDec", "sTurbo"].forEach((id) => $(id).classList.toggle("dis", !on));
  }

  function setBet(v) {
    bet = Math.max(cfg.min, Math.min(cfg.max, v));
    bet = Math.round(bet * 100) / 100;
    $("sBet").textContent = bet;
  }

  function doSpin(buy) {
    if (busy) return;
    if (window.Snd) Snd.unlock();
    const need = buy ? bet * 60 : bet;
    if ((window.BAL || 0) / 1e9 < need) { window.toast && toast("Недостаточно монет — нажми ＋"); return; }
    busy = true; enable(false);
    $("slotBanner").className = "slot-banner";
    if (window.Snd) Snd.click();
    window.sendWS && window.sendWS({ type: buy ? "slot_buy" : "slot_spin", amount: bet });
  }

  const SlotGame = {
    init() {
      buildGrid(); buildLadder(); setLadder(1);
      $("sSpin").onclick = () => doSpin(false);
      $("sBuy").onclick = () => { if (window.Snd) Snd.unlock(); doSpin(true); };
      $("sInc").onclick = () => { setBet(bet + (bet < 1 ? 0.5 : bet < 10 ? 1 : 5)); if (window.Snd) Snd.click(); };
      $("sDec").onclick = () => { setBet(bet - (bet <= 1 ? 0.5 : bet <= 10 ? 1 : 5)); if (window.Snd) Snd.click(); };
      $("sTurbo").onclick = () => { turbo = !turbo; $("sTurbo").classList.toggle("act", turbo); if (window.Snd) Snd.click(); };
      $("sAuto").onclick = () => { auto = !auto; $("sAuto").classList.toggle("act", auto); if (window.Snd) Snd.click(); if (auto && !busy) doSpin(false); };
      setBet(1);
    },
    setConfig(c) { if (c) { cfg = c; setBet(Math.max(cfg.min, Math.min(bet, cfg.max))); } },
    handle(m) { if (m.type === "slot_result") animate(m); },
    show() { /* при открытии */ if (window.Snd) Snd.unlock(); },
  };
  window.SlotGame = SlotGame;
})();
