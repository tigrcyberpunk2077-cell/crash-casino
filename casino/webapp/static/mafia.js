"use strict";
/* «Ночи 11A» — мафия. Комнаты по коду, ночь/день, голосование. window.MafiaGame */
(function () {
  const $ = (id) => document.getElementById(id);
  let S = null;            // последний снимок
  let endsIn = 0, ticker = null;

  function send(o) { window.sendWS && window.sendWS(o); if (window.Snd) Snd.click(); }
  function visible() { const v = $("view-mafia"); return v && !v.classList.contains("hidden"); }

  /* ---------- таймер ---------- */
  function stopT() { if (ticker) { clearInterval(ticker); ticker = null; } }
  function startT() {
    stopT();
    ticker = setInterval(() => {
      if (!S || (S.phase !== "night" && S.phase !== "day")) { stopT(); return; }
      endsIn = Math.max(0, endsIn - 0.25); paintHead();
    }, 250);
  }

  /* ---------- рендер ---------- */
  function show(html) { $("mafiaStart").classList.add("hidden"); $("mafiaRoom").classList.remove("hidden"); }
  function toStart() { stopT(); S = null; $("mafiaRoom").classList.add("hidden"); $("mafiaStart").classList.remove("hidden"); }

  function paintHead() {
    if (!S) return;
    const h = $("mafiaHead");
    let t = "";
    if (S.phase === "lobby") t = `Лобби · код <b>${S.code}</b> · ${S.players.length} игроков`;
    else if (S.phase === "night") t = `🌙 Ночь ${S.night}/${S.maxNights} · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "day") t = `☀️ День · СХОДКА · ${Math.ceil(endsIn)}с`;
    else if (S.phase === "ended") t = S.winner === "city" ? "🏆 Город победил!" : "💀 Мафия победила";
    h.innerHTML = t;
    h.className = "mafia-head " + S.phase;
  }

  function canAct() {
    if (!S) return false;
    const me = S.players.find((p) => p.id === S.you);
    if (!me || !me.alive) return false;
    if (S.phase === "day") return true;
    if (S.phase === "night") return ["mafia", "doctor", "detective"].indexOf(S.yourRole) >= 0;
    return false;
  }
  function actHint() {
    if (S.phase === "lobby") return S.you === S.hostId ? "Ты хост: добивай ботами и стартуй" : "Ждём, пока хост начнёт…";
    if (S.phase === "night") {
      if (!canAct()) return "🌙 Город спит… жди утра";
      return S.yourRole === "mafia" ? "🎯 Кого убрать этой ночью?"
        : S.yourRole === "doctor" ? "💨 Кого лечить?" : "💻 Кого проверить?";
    }
    if (S.phase === "day") return canAct() ? "🗳️ Голосуй, кого выгнать" : "☠️ Ты выбыл — наблюдай";
    return "";
  }

  function paint() {
    if (!S) return;
    show();
    paintHead();
    // твоя роль
    const role = $("mafiaRole");
    if (S.yourRoleRu && S.phase !== "lobby") {
      let extra = "";
      if (S.check) extra = ` · Проверка: <b style="color:${S.check.isMafia ? '#ff4d8a' : '#22ff9d'}">${S.check.name} — ${S.check.isMafia ? "МАФИЯ" : "чист"}</b>`;
      role.innerHTML = `Ты: <b>${S.yourRoleRu}</b>${extra}`;
      role.classList.remove("hidden");
    } else role.classList.add("hidden");
    // подсказка
    $("mafiaHint").textContent = actHint();
    // игроки
    const box = $("mafiaPlayers"); box.innerHTML = "";
    const mySel = S.phase === "night" ? S.yourTarget : S.phase === "day" ? S.yourVote : null;
    S.players.forEach((p) => {
      const c = document.createElement("div");
      c.className = "mp" + (p.alive ? "" : " dead") + (p.id === mySel ? " sel" : "") + (p.id === S.you ? " me" : "");
      const tag = p.role ? `<span class="mp-role">${p.roleRu || ""}</span>` : "";
      c.innerHTML = `<span class="mp-name">${p.bot ? "🤖 " : ""}${p.name}${p.id === S.you ? " (ты)" : ""}</span>${tag}` +
        (p.alive ? "" : `<span class="mp-x">✖</span>`);
      if (canAct() && p.alive && p.id !== S.you) {
        c.onclick = () => {
          if (S.phase === "night") send({ type: "mafia_night", target: p.id });
          else if (S.phase === "day") send({ type: "mafia_vote", target: p.id });
        };
      }
      box.appendChild(c);
    });
    // лента
    $("mafiaLog").innerHTML = (S.log || []).map((l) => `<div>${l}</div>`).join("");
    // контролы
    const ctr = $("mafiaCtrls"); ctr.innerHTML = "";
    if (S.phase === "lobby") {
      if (S.you === S.hostId) {
        const bb = btn("➕ Боты", () => { const n = prompt("Сколько ботов добавить?", "4"); if (n) send({ type: "mafia_addbots", n: parseInt(n) || 1 }); });
        const sb = btn(S.canStart ? "▶ Старт" : "Нужно 4+", () => send({ type: "mafia_start" }), S.canStart ? "primary" : "dis");
        ctr.append(bb, sb);
      }
      ctr.append(btn("Выйти", () => send({ type: "mafia_leave" })));
    } else if (S.phase === "ended") {
      ctr.append(btn("Выйти", () => send({ type: "mafia_leave" }), "primary"));
    } else {
      ctr.append(btn("Выйти", () => send({ type: "mafia_leave" })));
    }
  }
  function btn(text, on, cls) {
    const b = document.createElement("button");
    b.className = "mafia-btn " + (cls || ""); b.textContent = text; b.onclick = on; return b;
  }

  /* ---------- сообщения ---------- */
  function onSnap(m) {
    S = m; endsIn = m.endsIn || 0;
    paint();
    if (m.phase === "night" || m.phase === "day") startT(); else stopT();
    if (m.phase === "ended" && window.Snd) Snd.bigwin();
  }

  const MafiaGame = {
    init() {
      $("mafiaCreate").onclick = () => send({ type: "mafia_create" });
      $("mafiaJoin").onclick = () => {
        const code = ($("mafiaCode").value || "").trim().toUpperCase();
        if (code.length >= 4) send({ type: "mafia_join", code });
        else window.toast && toast("Введи код комнаты");
      };
    },
    handle(m) {
      if (m.type === "mafia") onSnap(m);
      else if (m.type === "mafia_timer") { if (S && (S.phase === m.phase)) { endsIn = m.endsIn; paintHead(); } }
      else if (m.type === "mafia_left") toStart();
    },
    show() { if (window.Snd) Snd.unlock(); if (S) send({ type: "mafia_state" }); },
  };
  window.MafiaGame = MafiaGame;
})();
