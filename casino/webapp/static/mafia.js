"use strict";
/* «Ночи 11A» — мафия. Лобби с выбором персонажа → город на карте (выбор дома) →
   ночь/день/голосование. window.MafiaGame */
(function () {
  const $ = (id) => document.getElementById(id);
  const V = "?v=26";
  const CHAR_NAME = { matin: "Матин", gorila: "Громила", samira: "Самира", rusik: "Русик",
    baran: "Баран", pastuh: "Пастух", gryaz: "Грязь", dima: "Дима", kolya: "Коля" };
  const avatar = (ch) => "/static/cyber/card_" + ch + ".jpg" + V;

  let S = null, endsIn = 0, ticker = null;

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
    const h = $("mafiaHead");
    let t = "";
    if (S.phase === "lobby") t = `Лобби · код <b>${S.code}</b> · ${S.players.length} 👥`;
    else if (S.phase === "city") t = `🏙️ Город «11A» · выбор дома · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "night") t = `🌙 Ночь ${S.night}/${S.maxNights} · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "day") t = `☀️ СХОДКА · голосуем · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "ended") t = S.winner === "city" ? "🏆 ГОРОД ПОБЕДИЛ!" : "💀 МАФИЯ ПОБЕДИЛА";
    h.innerHTML = t; h.className = "mafia-head " + S.phase;
  }

  function me() { return S && S.players.find((p) => p.id === S.you); }
  function canAct() {
    const m = me();
    if (!m || !m.alive) return false;
    if (S.phase === "day") return true;
    if (S.phase === "night") return ["mafia", "doctor", "detective"].indexOf(S.yourRole) >= 0;
    return false;
  }
  function actHint() {
    if (S.phase === "lobby") return S.you === S.hostId ? "Ты хост: выбери перса, добей ботами и стартуй" : "Выбери персонажа и жди старта…";
    if (S.phase === "city") return S.yourHouse ? "✅ Дом выбран. Жди ночь…" : "🗺️ Тапни на карте, куда пойти";
    if (S.phase === "night") {
      if (!canAct()) return "🌙 Город спит… жди утра";
      return S.yourRole === "mafia" ? "🎯 Кого убрать?" : S.yourRole === "doctor" ? "💨 Кого лечить?" : "💻 Кого проверить?";
    }
    if (S.phase === "day") return canAct() ? "🗳️ Жми на игрока — кого выгнать" : "☠️ Ты выбыл — наблюдай";
    return "";
  }

  /* ---------- блоки ---------- */
  function playerGrid() {
    const box = document.createElement("div"); box.className = "mafia-players";
    const sel = S.phase === "night" ? S.yourTarget : S.phase === "day" ? S.yourVote : null;
    S.players.forEach((p) => {
      const c = document.createElement("div");
      c.className = "mp" + (p.alive ? "" : " dead") + (p.id === sel ? " sel" : "") + (p.id === S.you ? " me" : "");
      const av = p.char ? `<img class="mp-av" src="${avatar(p.char)}" alt="">` : `<div class="mp-av noav">👤</div>`;
      const role = p.role ? `<span class="mp-role">${p.roleRu || ""}</span>` : "";
      c.innerHTML = `${av}<div class="mp-info"><span class="mp-name">${p.bot ? "🤖" : ""}${p.name}${p.id === S.you ? " (ты)" : ""}</span>${role}</div>` +
        (p.alive ? "" : `<span class="mp-x">✖</span>`);
      if (canAct() && p.alive && p.id !== S.you) {
        c.onclick = () => send({ type: S.phase === "night" ? "mafia_night" : "mafia_vote", target: p.id });
      }
      box.appendChild(c);
    });
    return box;
  }

  function lobbyBlock() {
    const wrap = document.createElement("div");
    const t = document.createElement("div"); t.className = "pick-title"; t.textContent = "🎭 Выбери персонажа";
    wrap.appendChild(t);
    const strip = document.createElement("div"); strip.className = "char-strip";
    (S.chars || []).forEach((ch) => {
      const b = document.createElement("button");
      b.className = "char-pick" + (S.yourChar === ch ? " sel" : "");
      b.innerHTML = `<img src="${avatar(ch)}" alt=""><small>${CHAR_NAME[ch] || ch}</small>`;
      b.onclick = () => send({ type: "mafia_char", char: ch });
      strip.appendChild(b);
    });
    wrap.appendChild(strip);
    const pt = document.createElement("div"); pt.className = "pick-title"; pt.textContent = `👥 Игроки (${S.players.length})`;
    wrap.appendChild(pt);
    wrap.appendChild(playerGrid());
    return wrap;
  }

  function cityBlock() {
    const wrap = document.createElement("div");
    const map = document.createElement("div"); map.className = "mafia-map";
    const img = document.createElement("img"); img.src = "/static/cyber/map.jpg" + V; img.alt = "";
    map.appendChild(img);
    (S.houses || []).forEach((h) => {
      const pin = document.createElement("button");
      const cnt = S.players.filter((p) => p.house === h.id).length;
      pin.className = "house-pin" + (S.yourHouse === h.id ? " sel" : "");
      pin.style.left = h.x + "%"; pin.style.top = h.y + "%";
      pin.innerHTML = `<span class="hp-emoji">${h.emoji}</span><span class="hp-name">${h.name}${cnt ? " ·" + cnt : ""}</span>`;
      pin.onclick = () => send({ type: "mafia_house", house: h.id });
      map.appendChild(pin);
    });
    wrap.appendChild(map);
    return wrap;
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
    $("mafiaHint").textContent = actHint();

    const body = $("mafiaBody"); body.innerHTML = "";
    if (S.phase === "lobby") body.appendChild(lobbyBlock());
    else if (S.phase === "city") body.appendChild(cityBlock());
    else body.appendChild(playerGrid());

    $("mafiaLog").innerHTML = (S.log || []).map((l) => `<div>${l}</div>`).join("");

    const ctr = $("mafiaCtrls"); ctr.innerHTML = "";
    if (S.phase === "lobby" && S.you === S.hostId) {
      ctr.append(btn("➕ Боты", () => { const n = prompt("Сколько ботов добавить?", "4"); if (n) send({ type: "mafia_addbots", n: parseInt(n) || 1 }); }));
      ctr.append(btn(S.canStart ? "▶ Старт" : "Нужно 4+ игроков", () => send({ type: "mafia_start" }), S.canStart ? "primary" : "dis"));
    }
    ctr.append(btn(S.phase === "ended" ? "🏠 В лобби" : "Выйти", () => send({ type: "mafia_leave" }), S.phase === "ended" ? "primary" : ""));
  }
  function btn(text, on, cls) {
    const b = document.createElement("button"); b.className = "mafia-btn " + (cls || "");
    b.textContent = text; b.onclick = on; return b;
  }

  function onSnap(m) {
    const wasEnded = S && S.phase === "ended";
    S = m; endsIn = m.endsIn || 0; paint();
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
