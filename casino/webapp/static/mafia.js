"use strict";
/* «Ночи 11A» — мафия. Лобби (выбор перса) → город (карта) → ночь (first-person
   локация + клип сна + роль) → день (СХОДКА в голосарии) → итог. window.MafiaGame */
(function () {
  const $ = (id) => document.getElementById(id);
  const V = "?v=28";
  const CHAR_NAME = { matin: "Матин", gorila: "Громила", samira: "Самира", rusik: "Русик",
    baran: "Баран", pastuh: "Пастух", gryaz: "Грязь", dima: "Дима", kolya: "Коля" };
  const avatar = (ch) => "/static/cyber/card_" + (ch || "matin") + ".jpg" + V;
  const locImg = (id) => "/static/cyber/loc/" + id + ".jpg" + V;
  const SEATS = [[16, 56], [15, 78], [84, 56], [85, 78], [37, 86], [63, 86], [33, 41], [67, 41]];

  let S = null, endsIn = 0, ticker = null, lastSleep = 0;

  function send(o) { window.sendWS && window.sendWS(o); if (window.Snd) Snd.click(); }

  function stopT() { if (ticker) { clearInterval(ticker); ticker = null; } }
  function startT() {
    stopT();
    ticker = setInterval(() => {
      if (!S || ["city", "night", "day"].indexOf(S.phase) < 0) { stopT(); return; }
      endsIn = Math.max(0, endsIn - 0.25); paintHead();
    }, 250);
  }
  function toStart() { stopT(); S = null; $("mafiaRoom").classList.add("hidden"); $("mafiaStart").classList.remove("hidden"); }
  function showRoom() { $("mafiaStart").classList.add("hidden"); $("mafiaRoom").classList.remove("hidden"); }

  function paintHead() {
    if (!S) return;
    const h = $("mafiaHead"); let t = "";
    if (S.phase === "lobby") t = `Лобби · код <b>${S.code}</b> · ${S.players.length} 👥`;
    else if (S.phase === "city") t = `🏙️ Куда пойдёшь? · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "night") t = `🌙 Ночь ${S.night}/${S.maxNights} · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "day") t = `☀️ СХОДКА · голосуем · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "ended") t = S.winner === "city" ? "🏆 ГОРОД ПОБЕДИЛ!" : "💀 МАФИЯ ПОБЕДИЛА";
    h.innerHTML = t; h.className = "mafia-head " + S.phase;
  }

  function me() { return S && S.players.find((p) => p.id === S.you); }
  function canAct() {
    const m = me(); if (!m || !m.alive) return false;
    if (S.phase === "day") return true;
    if (S.phase === "night") return ["mafia", "doctor", "detective"].indexOf(S.yourRole) >= 0;
    return false;
  }
  function actHint() {
    if (S.phase === "night") return S.yourRole === "mafia" ? "🎯 Кого убрать?" : S.yourRole === "doctor" ? "💨 Кого лечить?" : "💻 Кого проверить?";
    return "";
  }

  /* ---------- список целей (ночь) ---------- */
  function playerGrid() {
    const box = document.createElement("div"); box.className = "mafia-players";
    const sel = S.yourTarget;
    S.players.forEach((p) => {
      const c = document.createElement("div");
      c.className = "mp" + (p.alive ? "" : " dead") + (p.id === sel ? " sel" : "") + (p.id === S.you ? " me" : "");
      const av = p.char ? `<img class="mp-av" src="${avatar(p.char)}">` : `<div class="mp-av noav">👤</div>`;
      c.innerHTML = `${av}<div class="mp-info"><span class="mp-name">${p.bot ? "🤖" : ""}${p.name}${p.id === S.you ? " (ты)" : ""}</span></div>` + (p.alive ? "" : `<span class="mp-x">✖</span>`);
      if (canAct() && p.alive && p.id !== S.you) c.onclick = () => send({ type: "mafia_night", target: p.id });
      box.appendChild(c);
    });
    return box;
  }

  /* ---------- лобби: выбор персонажа ---------- */
  function lobbyBlock() {
    const wrap = document.createElement("div");
    const t = document.createElement("div"); t.className = "pick-title"; t.textContent = "🎭 Выбери персонажа"; wrap.appendChild(t);
    const strip = document.createElement("div"); strip.className = "char-strip";
    (S.chars || []).forEach((ch) => {
      const b = document.createElement("button"); b.className = "char-pick" + (S.yourChar === ch ? " sel" : "");
      b.innerHTML = `<img src="${avatar(ch)}"><small>${CHAR_NAME[ch] || ch}</small>`;
      b.onclick = () => send({ type: "mafia_char", char: ch }); strip.appendChild(b);
    });
    wrap.appendChild(strip);
    const pt = document.createElement("div"); pt.className = "pick-title"; pt.textContent = `👥 Игроки (${S.players.length})`; wrap.appendChild(pt);
    const grid = document.createElement("div"); grid.className = "mafia-players";
    S.players.forEach((p) => {
      const c = document.createElement("div"); c.className = "mp" + (p.id === S.you ? " me" : "");
      const av = p.char ? `<img class="mp-av" src="${avatar(p.char)}">` : `<div class="mp-av noav">👤</div>`;
      c.innerHTML = `${av}<div class="mp-info"><span class="mp-name">${p.bot ? "🤖" : ""}${p.name}${p.id === S.you ? " (ты)" : ""}</span></div>`;
      grid.appendChild(c);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  /* ---------- город: карта с локациями ---------- */
  function cityBlock() {
    const wrap = document.createElement("div");
    const banner = document.createElement("div"); banner.className = "city-banner";
    banner.style.backgroundImage = `url(/static/cyber/map.jpg${V})`;
    banner.innerHTML = `<span>🏙️ Куда пойдёшь этой ночью?</span>`;
    wrap.appendChild(banner);
    const grid = document.createElement("div"); grid.className = "loc-grid";
    (S.houses || []).forEach((h) => {
      const cnt = S.players.filter((p) => p.house === h.id).length;
      const card = document.createElement("button");
      card.className = "loc-card" + (S.yourHouse === h.id ? " sel" : "");
      card.innerHTML = `<img src="/static/cyber/loc/${h.id}.jpg${V}" alt="">` +
        `<span class="lc-name">${h.emoji} ${h.name}</span>` +
        (cnt ? `<span class="lc-cnt">${cnt}👤</span>` : "");
      card.onclick = () => send({ type: "mafia_house", house: h.id });
      grid.appendChild(card);
    });
    wrap.appendChild(grid);
    return wrap;
  }

  /* ---------- ночь: first-person локация ---------- */
  function nightBlock() {
    const wrap = document.createElement("div");
    const m = me();
    const locId = (m && m.house) || "kvartira";
    const loc = (S.houses || []).find((h) => h.id === locId);
    const scene = document.createElement("div"); scene.className = "loc-scene";
    scene.style.backgroundImage = `url(${locImg(locId)})`;
    const lab = document.createElement("div"); lab.className = "loc-label";
    lab.innerHTML = `🌙 Ты в: <b>${loc ? loc.emoji + " " + loc.name : "Дома"}</b>`;
    scene.appendChild(lab);
    const co = S.players.filter((p) => p.house === locId && p.id !== S.you);
    const row = document.createElement("div"); row.className = "loc-people";
    if (co.length) {
      co.forEach((p) => {
        const a = document.createElement("div"); a.className = "loc-av" + (p.alive ? "" : " dead");
        a.innerHTML = `<img src="${avatar(p.char)}"><small>${p.name}</small>`; row.appendChild(a);
      });
    } else {
      const e = document.createElement("div"); e.className = "loc-solo"; e.textContent = "Ты здесь один…"; row.appendChild(e);
    }
    scene.appendChild(row);
    wrap.appendChild(scene);
    if (canAct()) {
      const ht = document.createElement("div"); ht.className = "pick-title"; ht.textContent = actHint(); wrap.appendChild(ht);
      wrap.appendChild(playerGrid());
    }
    return wrap;
  }

  /* ---------- день: голосарий с креслами ---------- */
  function dayBlock() {
    const wrap = document.createElement("div");
    const room = document.createElement("div"); room.className = "golos-room";
    room.style.backgroundImage = `url(/static/cyber/loc/golosarij.jpg${V})`;
    const seated = S.players.slice(0, SEATS.length);
    seated.forEach((p, i) => {
      const s = SEATS[i];
      const seat = document.createElement("button");
      seat.className = "seat" + (p.alive ? "" : " dead") + (S.yourVote === p.id ? " voted" : "") + (p.id === S.you ? " me" : "");
      seat.style.left = s[0] + "%"; seat.style.top = s[1] + "%";
      seat.innerHTML = `<img src="${avatar(p.char)}"><span>${p.bot ? "🤖" : ""}${p.name}</span>`;
      if (canAct() && p.alive && p.id !== S.you) seat.onclick = () => send({ type: "mafia_vote", target: p.id });
      room.appendChild(seat);
    });
    wrap.appendChild(room);
    if (S.players.length > SEATS.length) {
      const more = document.createElement("div"); more.className = "mafia-players";
      S.players.slice(SEATS.length).forEach((p) => {
        const c = document.createElement("div");
        c.className = "mp" + (p.alive ? "" : " dead") + (S.yourVote === p.id ? " sel" : "");
        c.innerHTML = `<img class="mp-av" src="${avatar(p.char)}"><div class="mp-info"><span class="mp-name">${p.name}</span></div>`;
        if (canAct() && p.alive && p.id !== S.you) c.onclick = () => send({ type: "mafia_vote", target: p.id });
        more.appendChild(c);
      });
      wrap.appendChild(more);
    }
    return wrap;
  }

  /* ---------- клип сна ---------- */
  function playSleep() {
    let ov = $("mafiaSleep");
    if (!ov) {
      ov = document.createElement("div"); ov.id = "mafiaSleep"; ov.className = "sleep-ov";
      ov.innerHTML = `<video src="/static/cyber/loc/sleep.mp4${V}" muted playsinline></video><div class="sleep-txt">🌙 Город засыпает…</div>`;
      $("view-mafia").appendChild(ov);
    }
    ov.classList.add("on");
    const v = ov.querySelector("video"); try { v.currentTime = 0; v.play(); } catch (e) {}
    clearTimeout(window._sleepT); window._sleepT = setTimeout(() => ov.classList.remove("on"), 4500);
  }

  function paint() {
    if (!S) return;
    showRoom(); paintHead();
    const role = $("mafiaRole");
    if (S.yourRoleRu && S.phase !== "lobby") {
      let extra = "";
      if (S.check) extra = ` · 🔎 <b style="color:${S.check.isMafia ? '#ff4d8a' : '#22ff9d'}">${S.check.name}: ${S.check.isMafia ? "МАФИЯ" : "чист"}</b>`;
      role.innerHTML = `Ты: <b>${S.yourRoleRu}</b>${extra}`; role.classList.remove("hidden");
    } else role.classList.add("hidden");
    $("mafiaHint").textContent = S.phase === "city" ? (S.yourHouse ? "✅ Место выбрано" : "🗺️ Тапни локацию на карте") :
      S.phase === "day" ? (canAct() ? "🗳️ Жми на участника — кого выгнать" : "☠️ Ты выбыл") :
      S.phase === "lobby" ? (S.you === S.hostId ? "Ты хост: добей ботами и стартуй" : "Жди старта…") : "";

    const body = $("mafiaBody"); body.innerHTML = "";
    if (S.phase === "lobby") body.appendChild(lobbyBlock());
    else if (S.phase === "city") body.appendChild(cityBlock());
    else if (S.phase === "night") body.appendChild(nightBlock());
    else if (S.phase === "day") body.appendChild(dayBlock());
    else body.appendChild(playerGrid());

    $("mafiaLog").innerHTML = (S.log || []).map((l) => `<div>${l}</div>`).join("");

    const ctr = $("mafiaCtrls"); ctr.innerHTML = "";
    if (S.phase === "lobby" && S.you === S.hostId) {
      ctr.append(btn("➕ Бот", () => send({ type: "mafia_addbots", n: 1 })));
      ctr.append(btn("🤖 +3", () => send({ type: "mafia_addbots", n: 3 })));
      ctr.append(btn(S.canStart ? "▶ Старт" : "Нужно 4+", () => send({ type: "mafia_start" }), S.canStart ? "primary" : "dis"));
    }
    ctr.append(btn(S.phase === "ended" ? "🏠 В лобби" : "Выйти", () => send({ type: "mafia_leave" }), S.phase === "ended" ? "primary" : ""));
  }
  function btn(text, on, cls) {
    const b = document.createElement("button"); b.className = "mafia-btn " + (cls || "");
    b.textContent = text; b.onclick = on; return b;
  }

  function onSnap(m) {
    const wasEnded = S && S.phase === "ended";
    const newNight = m.phase === "night" && m.night !== lastSleep;
    S = m; endsIn = m.endsIn || 0; paint();
    if (newNight) { lastSleep = m.night; playSleep(); }
    if (["city", "night", "day"].indexOf(m.phase) >= 0) startT(); else stopT();
    if (m.phase === "ended" && !wasEnded && window.Snd) Snd.bigwin();
  }

  const MafiaGame = {
    init() {
      $("mafiaCreate").onclick = () => send({ type: "mafia_create" });
      $("mafiaJoin").onclick = () => {
        const code = ($("mafiaCode").value || "").trim().toUpperCase();
        if (code.length >= 4) send({ type: "mafia_join", code }); else window.toast && toast("Введи код комнаты");
      };
    },
    handle(m) {
      if (m.type === "mafia") onSnap(m);
      else if (m.type === "mafia_timer") { if (S && S.phase === m.phase) { endsIn = m.endsIn; paintHead(); } }
      else if (m.type === "mafia_left") toStart();
    },
    show() { if (window.Snd) Snd.unlock(); if (S) send({ type: "mafia_state" }); },
  };
  window.MafiaGame = MafiaGame;
})();
